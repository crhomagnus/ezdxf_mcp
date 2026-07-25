#!/usr/bin/env python3
"""
image.primitives — vocabulario unificado de ajuste.

Em vez de escolher UM modo para o arquivo inteiro, cada trecho do contorno
recebe a primitiva que melhor o descreve, e cada contorno fechado e testado
antes contra as formas analiticas.

Vocabulario, em ordem de custo (numero de parametros):

    CIRCULO   CIRCLE            3 params   contorno fechado redondo
    ELIPSE    ELLIPSE           5 params   contorno fechado eliptico
    RETA      segmento          2 pontos   trecho reto
    ARCO      bulge na polilinha  +1 num   trecho de raio constante
    BEZIER    SPLINE grau 3      8 params  curvatura variavel

Regra de escolha: entre as primitivas que cabem na tolerancia, vence a de
MENOR custo. A reta ganha empates — e a mais simples e a mais compativel.

Container de saida:
  - so reta e arco      -> LWPOLYLINE com bulge (compativel ate R12)
  - qualquer Bezier     -> HATCH/EdgePath ou entidades separadas, porque a
                           LWPOLYLINE nao carrega Bezier. O EdgePath do HATCH
                           e o unico container do DXF que aceita reta, arco,
                           elipse e spline no mesmo contorno fechado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import bezierfit, curvefit

# custo relativo por primitiva — usado para desempate
CUSTO = {"reta": 1, "arco": 2, "bezier": 6}


@dataclass
class Trecho:
    """Um pedaco do contorno com a primitiva escolhida."""
    i: int
    j: int
    tipo: str                       # reta | arco | bezier
    erro: float
    centro: tuple = (0.0, 0.0)      # arco
    raio: float = 0.0               # arco
    curvas: list = field(default_factory=list)   # bezier: lista de (4,2)


@dataclass
class Forma:
    """Resultado do ajuste de um contorno inteiro."""
    tipo: str                       # circulo | elipse | composta
    trechos: list = field(default_factory=list)
    # circulo
    centro: tuple = (0.0, 0.0)
    raio: float = 0.0
    # elipse
    eixo_maior: tuple = (0.0, 0.0)
    razao: float = 1.0
    erro: float = 0.0

    @property
    def precisa_hatch(self) -> bool:
        """True quando o contorno mistura Bezier com reta/arco."""
        tipos = {t.tipo for t in self.trechos}
        return "bezier" in tipos and len(tipos) > 1

    def resumo(self) -> dict:
        d = {"reta": 0, "arco": 0, "bezier": 0}
        for t in self.trechos:
            d[t.tipo] += len(t.curvas) if t.tipo == "bezier" else 1
        return d


# ---------------------------------------------------------------------------
# formas analiticas do contorno inteiro
# ---------------------------------------------------------------------------
def _erro_circulo(p, centro, raio) -> float:
    return float(np.abs(np.hypot(p[:, 0] - centro[0], p[:, 1] - centro[1]) - raio).max())


def _erro_elipse(p, centro, eixos, ang_deg) -> float:
    """Desvio maximo a elipse, medido no espaco normalizado e reescalado.

    Aproximacao: leva o ponto ao circulo unitario pela transformacao inversa
    da elipse, mede o desvio radial e multiplica pelo semieixo MENOR — que e
    o limite inferior da distancia real, entao a estimativa e conservadora.
    """
    a, b = eixos[0] / 2.0, eixos[1] / 2.0
    if a <= 0 or b <= 0:
        return float("inf")
    t = math.radians(ang_deg)
    c, s = math.cos(t), math.sin(t)
    dx, dy = p[:, 0] - centro[0], p[:, 1] - centro[1]
    u = (dx * c + dy * s) / a
    v = (-dx * s + dy * c) / b
    return float(np.abs(np.hypot(u, v) - 1.0).max() * min(a, b))


def ajustar_forma_fechada(p: np.ndarray, tol: float, permitidas: set):
    """Tenta descrever o contorno inteiro por uma forma analitica.

    Devolve Forma ou None. Circulo antes de elipse: 3 parametros contra 5.
    """
    import cv2

    if len(p) < 6:
        return None
    cnt: np.ndarray = p.astype(np.float32).reshape(-1, 1, 2)

    if "circulo" in permitidas:
        (cx, cy), r = cv2.minEnclosingCircle(cnt)
        area = cv2.contourArea(cnt)
        if r > 0 and area > 0:
            r_area = math.sqrt(area / math.pi)
            raio = (r + r_area) / 2.0        # equilibra os dois vieses
            e = _erro_circulo(p, (cx, cy), raio)
            if e <= tol:
                return Forma("circulo", centro=(cx, cy), raio=raio, erro=e)

    if "elipse" in permitidas and len(p) >= 8:
        try:
            (cx, cy), (MA, ma), ang = cv2.fitEllipse(cnt)
        except cv2.error:
            return None
        e = _erro_elipse(p, (cx, cy), (MA, ma), ang)
        if e <= tol and MA > 0 and ma > 0:
            # cv2.fitEllipse devolve (largura, altura) do retangulo girado.
            # A LARGURA fica na direcao 'ang'; a ALTURA em 'ang + 90'.
            # Qualquer das duas pode ser o eixo maior — decide o comprimento,
            # nao a ordem. Trocar isso produz uma elipse girada 90 graus:
            # medido, dava 60 px de erro contra 0,004 px na versao correta.
            if MA >= ma:
                L, w, rot = MA, ma, math.radians(ang)
            else:
                L, w, rot = ma, MA, math.radians(ang + 90.0)
            eixo = (L / 2.0 * math.cos(rot), L / 2.0 * math.sin(rot))
            razao = w / L
            return Forma("elipse", centro=(cx, cy), eixo_maior=eixo,
                         razao=razao, erro=e)
    return None


# ---------------------------------------------------------------------------
# escolha por trecho
# ---------------------------------------------------------------------------
def ajustar_contorno(pontos, tol: float = 1.0, tol_bezier: float | None = None,
                     permitidas: set | None = None, fechado: bool = True,
                     ang_max: float = 120.0) -> Forma:
    """Ajusta um contorno com o vocabulario completo.

    1. tenta descrever o contorno inteiro como CIRCULO ou ELIPSE
    2. se nao couber, segmenta em RETA e ARCO
    3. onde nem reta nem arco cabem, usa BEZIER

    O passo 3 e a diferenca para o segmentador antigo, que caia em reta
    quando nao conseguia arco — poligonalizando justamente os trechos de
    curvatura variavel, que sao os que mais precisam de curva.
    """
    permitidas = permitidas or {"circulo", "elipse", "reta", "arco", "bezier"}
    tol_bezier = tol if tol_bezier is None else tol_bezier
    p = np.asarray(pontos, dtype=float)

    if fechado:
        forma = ajustar_forma_fechada(p, tol, permitidas)
        if forma is not None:
            return forma

    # segmentacao reta/arco
    if "arco" in permitidas or "reta" in permitidas:
        raio_max = 1e5 if "arco" in permitidas else 0.0
        segs = curvefit.segmentar(p, tol=tol, raio_max=raio_max, ang_max=ang_max)
    else:
        segs = []

    trechos: list[Trecho] = []
    for s in segs:
        sub = p[s.i:s.j + 1]
        # reta longa com erro alto é candidata a Bezier: a segmentacao aceita
        # reta como ultimo recurso, e e exatamente ali que a curva se perde
        vale_bezier = ("bezier" in permitidas and s.tipo == "reta"
                       and s.erro > tol * 0.6 and len(sub) >= 6)
        if vale_bezier:
            curvas = bezierfit.ajustar(sub, tol=tol_bezier, fechado=False)
            e_bez = bezierfit.erro_real(sub, curvas) if curvas else float("inf")
            if curvas and e_bez < s.erro:
                trechos.append(Trecho(s.i, s.j, "bezier", e_bez, curvas=curvas))
                continue
        trechos.append(Trecho(s.i, s.j, s.tipo, s.erro, s.centro, s.raio))

    if not trechos and "bezier" in permitidas:
        curvas = bezierfit.ajustar(p, tol=tol_bezier, fechado=fechado)
        if curvas:
            trechos = [Trecho(0, len(p) - 1, "bezier",
                              bezierfit.erro_real(p, curvas), curvas=curvas)]

    return Forma("composta", trechos=trechos)


# ---------------------------------------------------------------------------
# emissao para DXF
# ---------------------------------------------------------------------------
def emitir(msp, forma: Forma, pontos, altura_px: int, escala: float,
           camada: str, camada_circulo: str | None = None) -> str:
    """Grava a forma no modelspace. Devolve o tipo de container usado."""
    p = np.asarray(pontos, dtype=float)

    def tf(xy):
        return float(xy[0]) * escala, float(altura_px - xy[1]) * escala

    if forma.tipo == "circulo":
        cx, cy = forma.centro
        msp.add_circle(center=(cx * escala, (altura_px - cy) * escala),
                       radius=forma.raio * escala,
                       dxfattribs={"layer": camada_circulo or camada})
        return "CIRCLE"

    if forma.tipo == "elipse":
        cx, cy = forma.centro
        ex, ey = forma.eixo_maior
        # o eixo maior e um VETOR a partir do centro; o Y espelha junto
        msp.add_ellipse(center=(cx * escala, (altura_px - cy) * escala),
                        major_axis=(ex * escala, -ey * escala),
                        ratio=forma.razao,
                        dxfattribs={"layer": camada_circulo or camada})
        return "ELLIPSE"

    tipos = {t.tipo for t in forma.trechos}

    # caminho simples: so reta e arco -> LWPOLYLINE com bulge
    if "bezier" not in tipos:
        segs = [curvefit.Segmento(t.i, t.j, t.tipo, t.erro, t.centro, t.raio)
                for t in forma.trechos]
        verts = curvefit.para_bulge(p, segs, transformar=tf)
        if len(verts) >= 3:
            msp.add_lwpolyline(verts, format="xyseb", close=True,
                               dxfattribs={"layer": camada})
            return "LWPOLYLINE"
        return "descartado"

    # vocabulario misto -> EdgePath do HATCH, o unico container que aceita
    # reta, arco, elipse e spline no mesmo contorno fechado
    h = msp.add_hatch(dxfattribs={"layer": camada})
    h.set_solid_fill()
    ep = h.paths.add_edge_path()
    for t in forma.trechos:
        if t.tipo == "bezier":
            for c in t.curvas:
                ep.add_spline(control_points=[tf(c[0]), tf(c[1]),
                                              tf(c[2]), tf(c[3])], degree=3)
        elif t.tipo == "arco":
            ini, fim = tf(p[t.i]), tf(p[t.j])
            cx, cy = t.centro
            c = (cx * escala, (altura_px - cy) * escala)
            a0 = math.degrees(math.atan2(ini[1] - c[1], ini[0] - c[0]))
            a1 = math.degrees(math.atan2(fim[1] - c[1], fim[0] - c[0]))
            ep.add_arc(center=c, radius=t.raio * escala,
                       start_angle=a0, end_angle=a1)
        else:
            ep.add_line(tf(p[t.i]), tf(p[t.j]))
    return "HATCH"
