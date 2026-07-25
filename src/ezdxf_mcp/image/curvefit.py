#!/usr/bin/env python3
"""
image.curvefit — ajusta RETAS e ARCOS a uma sequencia densa de pontos.

Resolve o problema de curva suave virar poligono: em vez de jogar fora
pontos com approxPolyDP, o contorno e segmentado em trechos que sao reta
ou arco de circunferencia, dentro de uma tolerancia declarada.

O arco sai como *bulge* na LWPOLYLINE — a representacao nativa do DXF para
arco dentro de polilinha. Todo CAM le isso, e a polilinha explode em ARC
de verdade, nao em corda.

Algoritmo: split-and-merge.
  1. tenta ajustar UMA primitiva (reta ou arco) ao trecho inteiro
  2. se o desvio maximo passa da tolerancia, quebra no ponto de pior
     desvio e repete nos dois lados
  3. junta trechos vizinhos quando a juncao ainda cabe na tolerancia
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Segmento:
    """Trecho ajustado do contorno."""
    i: int                       # indice inicial no array de pontos
    j: int                       # indice final (inclusive)
    tipo: str                    # "reta" | "arco"
    erro: float                  # desvio maximo em px
    centro: tuple = (0.0, 0.0)   # so para arco
    raio: float = 0.0            # so para arco


# ---------------------------------------------------------------------------
# ajuste de primitivas
# ---------------------------------------------------------------------------
def ajustar_circulo(p: np.ndarray):
    """Minimos quadrados algebricos (Kasa), com centragem para estabilidade.

    Devolve ((cx, cy), r) ou None se o sistema for degenerado — o caso
    tipico de degeneracao e o trecho ser reto, e ai reta e a resposta certa.
    """
    if len(p) < 3:
        return None
    m = p.mean(axis=0)
    u, v = p[:, 0] - m[0], p[:, 1] - m[1]
    Suu, Svv, Suv = (u * u).sum(), (v * v).sum(), (u * v).sum()
    A = np.array([[Suu, Suv], [Suv, Svv]])
    if abs(np.linalg.det(A)) < 1e-12:
        return None
    b = 0.5 * np.array([(u * u * u).sum() + (u * v * v).sum(),
                        (v * v * v).sum() + (v * u * u).sum()])
    try:
        uc, vc = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return None
    r2 = uc * uc + vc * vc + (Suu + Svv) / len(p)
    if r2 <= 0:
        return None
    return (uc + m[0], vc + m[1]), math.sqrt(r2)


def erro_reta(p: np.ndarray) -> float:
    """Desvio maximo dos pontos a reta que liga o primeiro ao ultimo."""
    if len(p) < 3:
        return 0.0
    a, b = p[0], p[-1]
    d = b - a
    n = math.hypot(d[0], d[1])
    if n < 1e-12:
        return float(np.hypot(*(p - a).T).max())
    # distancia ponto-reta pelo produto vetorial 2D
    offsets = p - a
    cross_2d = d[0] * offsets[:, 1] - d[1] * offsets[:, 0]
    return float(np.abs(cross_2d).max() / n)


def erro_arco(p: np.ndarray, centro, raio: float) -> float:
    """Desvio maximo dos pontos a circunferencia ajustada."""
    d = np.hypot(p[:, 0] - centro[0], p[:, 1] - centro[1])
    return float(np.abs(d - raio).max())


def indice_pior_reta(p: np.ndarray) -> int:
    a, b = p[0], p[-1]
    d = b - a
    n = math.hypot(d[0], d[1])
    if n < 1e-12:
        return len(p) // 2
    offsets = p - a
    cross_2d = d[0] * offsets[:, 1] - d[1] * offsets[:, 0]
    return int(np.argmax(np.abs(cross_2d) / n))


# ---------------------------------------------------------------------------
# segmentacao
# ---------------------------------------------------------------------------
def _angulo_varrido(p: np.ndarray, centro, raio: float) -> float:
    """Angulo total varrido pelo trecho, em graus, acumulado ponto a ponto.

    Necessario porque bulge = tan(theta/4): perto de 360 graus o valor
    explode, e a LWPOLYLINE nao consegue representar o arco.
    """
    ang = np.unwrap(np.arctan2(p[:, 1] - centro[1], p[:, 0] - centro[0]))
    return float(abs(ang[-1] - ang[0]) * 180.0 / math.pi)


def _classificar(p: np.ndarray, tol: float, raio_max: float,
                 ang_max: float = 120.0):
    """Escolhe a melhor primitiva para o trecho. Devolve (tipo, erro, centro, raio).

    A reta ganha o empate: e mais simples, e um 'arco' de raio gigantesco e
    uma reta disfarçada que so atrapalha o CAM.
    """
    e_reta = erro_reta(p)
    if e_reta <= tol:
        return "reta", e_reta, (0.0, 0.0), 0.0

    fit = ajustar_circulo(p)
    if fit is None:
        return None
    centro, raio = fit
    if raio > raio_max:                       # arco raso demais: e reta
        return None
    # corda longa com raio enorme e reta disfarcada; so atrapalha o CAM
    corda = math.hypot(p[-1, 0] - p[0, 0], p[-1, 1] - p[0, 1])
    if corda > 0 and raio / corda > 20.0:
        return None
    if _angulo_varrido(p, centro, raio) > ang_max:
        return None                           # forca a quebra em arcos menores
    e_arco = erro_arco(p, centro, raio)
    if e_arco <= tol:
        return "arco", e_arco, centro, raio
    return None


def segmentar(pontos: np.ndarray, tol: float = 1.0,
              raio_max: float = 1e5, min_pts_arco: int = 5,
              ang_max: float = 120.0) -> list[Segmento]:
    """Quebra o contorno em retas e arcos dentro da tolerancia.

    Parameters
    ----------
    pontos : (N,2) float
    tol : desvio maximo aceito, na mesma unidade dos pontos (px)
    raio_max : acima disso o arco vira reta
    min_pts_arco : arco exige pelo menos estes pontos, senao vira reta
    """
    p = np.asarray(pontos, dtype=float)
    n = len(p)
    if n < 2:
        return []
    if n == 2:
        return [Segmento(0, 1, "reta", 0.0)]

    saida: list[Segmento] = []

    def dividir(i: int, j: int) -> None:
        sub = p[i:j + 1]
        if len(sub) < 3:
            saida.append(Segmento(i, j, "reta", 0.0))
            return
        res = _classificar(sub, tol, raio_max, ang_max) if len(sub) >= min_pts_arco \
            else (("reta", erro_reta(sub), (0.0, 0.0), 0.0)
                  if erro_reta(sub) <= tol else None)
        if res is not None:
            tipo, err, centro, raio = res
            saida.append(Segmento(i, j, tipo, err, centro, raio))
            return
        k = i + indice_pior_reta(sub)
        if k <= i or k >= j:                  # nao houve progresso: aceita reta
            saida.append(Segmento(i, j, "reta", erro_reta(sub)))
            return
        dividir(i, k)
        dividir(k, j)

    dividir(0, n - 1)
    saida.sort(key=lambda s: s.i)
    return _fundir(p, saida, tol, raio_max, ang_max)


def _fundir(p: np.ndarray, segs: list[Segmento], tol: float,
            raio_max: float, ang_max: float = 120.0) -> list[Segmento]:
    """Junta vizinhos quando a uniao ainda cabe na tolerancia.

    O split puro fragmenta demais: uma curva longa vira varios arcos quase
    iguais. A fusao devolve o arco unico.
    """
    if len(segs) < 2:
        return segs
    saida = [segs[0]]
    for s in segs[1:]:
        a = saida[-1]
        if a.j != s.i:
            saida.append(s)
            continue
        sub = p[a.i:s.j + 1]
        res = _classificar(sub, tol, raio_max, ang_max)
        if res is not None:
            tipo, err, centro, raio = res
            saida[-1] = Segmento(a.i, s.j, tipo, err, centro, raio)
        else:
            saida.append(s)
    return saida


# ---------------------------------------------------------------------------
# saida: vertices com bulge para LWPOLYLINE
# ---------------------------------------------------------------------------
def para_bulge(pontos: np.ndarray, segs: list[Segmento],
               transformar=None) -> list[tuple]:
    """Converte a segmentacao em vertices no formato 'xyseb' da LWPOLYLINE.

    bulge = tan(angulo_incluido / 4); o sinal indica o sentido.
    Calculado a partir de tres pontos reais do arco, o que resolve
    magnitude e sinal de uma vez.
    """
    from ezdxf.math import Vec2, bulge_3_points

    p = np.asarray(pontos, dtype=float)
    tf = transformar or (lambda xy: (float(xy[0]), float(xy[1])))
    verts: list[tuple] = []

    for s in segs:
        ini = tf(p[s.i])
        if s.tipo == "arco":
            k = (s.i + s.j) // 2
            meio = tf(p[k])
            fim = tf(p[s.j])
            try:
                b = bulge_3_points(Vec2(ini), Vec2(fim), Vec2(meio))
            except Exception:
                b = 0.0
            if not math.isfinite(b) or abs(b) > 50:   # arco degenerado
                b = 0.0
            verts.append((ini[0], ini[1], 0.0, 0.0, b))
        else:
            verts.append((ini[0], ini[1], 0.0, 0.0, 0.0))

    if segs:
        f = tf(p[segs[-1].j])
        verts.append((f[0], f[1], 0.0, 0.0, 0.0))
    return verts
