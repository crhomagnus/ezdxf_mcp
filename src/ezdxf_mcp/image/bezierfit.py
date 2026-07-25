#!/usr/bin/env python3
"""
image.bezierfit — ajusta BEZIER CUBICA a uma sequencia densa de pontos.

Implementacao do algoritmo de Philip J. Schneider,
"An Algorithm for Automatically Fitting Digitized Curves",
Graphics Gems I (1990), pp. 612-626.

E o mesmo nucleo que o Potrace e os tracadores comerciais usam: minimos
quadrados com extremos e direcoes de tangente fixos, refinamento do
parametro por Newton-Raphson, e quebra recursiva no ponto de pior erro.

No DXF a Bezier cubica vira SPLINE de grau 3 — a conversao e EXATA,
porque uma Bezier cubica ja e uma B-spline de grau 3.
Exige DXF R2000 ou superior; R12 nao tem SPLINE.
"""

from __future__ import annotations

import numpy as np

MAX_ITER = 4          # iteracoes de Newton-Raphson por trecho
_EPS = 1e-12


# ---------------------------------------------------------------------------
# avaliacao de Bezier
# ---------------------------------------------------------------------------
def bezier_ponto(ctrl: np.ndarray, t: float) -> np.ndarray:
    """de Casteljau para grau 3."""
    mt = 1.0 - t
    return (mt ** 3 * ctrl[0] + 3 * mt * mt * t * ctrl[1]
            + 3 * mt * t * t * ctrl[2] + t ** 3 * ctrl[3])


def _q1(ctrl: np.ndarray, t: float) -> np.ndarray:
    """primeira derivada."""
    d = 3.0 * (ctrl[1:] - ctrl[:-1])
    mt = 1.0 - t
    return mt * mt * d[0] + 2 * mt * t * d[1] + t * t * d[2]


def _q2(ctrl: np.ndarray, t: float) -> np.ndarray:
    """segunda derivada."""
    d = 3.0 * (ctrl[1:] - ctrl[:-1])
    dd = 2.0 * (d[1:] - d[:-1])
    return (1.0 - t) * dd[0] + t * dd[1]


# ---------------------------------------------------------------------------
# tangentes e parametrizacao
# ---------------------------------------------------------------------------
def _norm(v: np.ndarray) -> np.ndarray:
    n = np.hypot(v[0], v[1])
    return v / n if n > _EPS else np.array([0.0, 0.0])


def _tangente_esq(p: np.ndarray, i: int) -> np.ndarray:
    return _norm(p[i + 1] - p[i])


def _tangente_dir(p: np.ndarray, i: int) -> np.ndarray:
    return _norm(p[i - 1] - p[i])


def _tangente_centro(p: np.ndarray, i: int) -> np.ndarray:
    """Tangente no ponto de quebra.

    Schneider: V1 = p[i-1]-p[i], V2 = p[i]-p[i+1], tangente = normalizar(V1+V2),
    que simplifica para p[i-1] - p[i+1] — a direcao da corda que atravessa o
    ponto de quebra.

    Escrever V1 - V2 (a segunda diferenca) e o erro facil de cometer aqui: ela
    aponta para o CENTRO DE CURVATURA, perpendicular a curva. Com esse engano,
    ajustar um circulo de 240 pontos produzia 170 Bezier em vez de 4.
    """
    return _norm(p[i - 1] - p[i + 1])


def _parametrizar(p: np.ndarray) -> np.ndarray:
    """Parametrizacao por comprimento de corda, normalizada em [0,1].

    E a estimativa inicial de t para cada ponto; o Newton-Raphson refina.
    """
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    return d / d[-1] if d[-1] > _EPS else np.linspace(0, 1, len(p))


# ---------------------------------------------------------------------------
# nucleo: minimos quadrados com extremos e tangentes fixos
# ---------------------------------------------------------------------------
def _gerar_bezier(p: np.ndarray, u: np.ndarray,
                  t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """Resolve as magnitudes alpha1 e alpha2 das tangentes por minimos quadrados.

    Os pontos de controle 0 e 3 sao os extremos do trecho; 1 e 2 ficam
    sobre as tangentes dadas, a distancias alpha1 e alpha2. So essas duas
    incognitas entram no sistema — por isso o ajuste preserva continuidade
    com o trecho vizinho.
    """
    mt = 1.0 - u
    b0 = mt ** 3
    b1 = 3.0 * mt * mt * u
    b2 = 3.0 * mt * u * u
    b3: np.ndarray = u ** 3

    a0 = t1[None, :] * b1[:, None]
    a1 = t2[None, :] * b2[:, None]

    c00 = float((a0 * a0).sum())
    c01 = float((a0 * a1).sum())
    c11 = float((a1 * a1).sum())

    base = p[0][None, :] * (b0 + b1)[:, None] + p[-1][None, :] * (b2 + b3)[:, None]
    tmp = p - base
    x0 = float((a0 * tmp).sum())
    x1 = float((a1 * tmp).sum())

    det = c00 * c11 - c01 * c01
    corda = float(np.hypot(*(p[-1] - p[0])))

    if abs(det) < _EPS:
        # sistema degenerado: heuristica de Wu/Barsky
        alpha1 = alpha2 = corda / 3.0
    else:
        alpha1 = (x0 * c11 - x1 * c01) / det
        alpha2 = (c00 * x1 - c01 * x0) / det

    # magnitude negativa ou absurda inverte a curva: cai na heuristica
    lim = corda * 3.0
    if alpha1 < _EPS or alpha2 < _EPS or alpha1 > lim or alpha2 > lim:
        alpha1 = alpha2 = corda / 3.0

    return np.array([p[0], p[0] + t1 * alpha1, p[-1] + t2 * alpha2, p[-1]])


def _reparametrizar(p: np.ndarray, u: np.ndarray, ctrl: np.ndarray) -> np.ndarray:
    """Um passo de Newton-Raphson em cada t, para aproximar o pe da perpendicular."""
    out = np.empty_like(u)
    for i, (pt, t) in enumerate(zip(p, u, strict=True)):
        d = bezier_ponto(ctrl, t) - pt
        q1 = _q1(ctrl, t)
        q2 = _q2(ctrl, t)
        den = float((q1 * q1).sum() + (d * q2).sum())
        out[i] = t if abs(den) < _EPS else t - float((d * q1).sum()) / den
    return np.clip(out, 0.0, 1.0)


def _erro_max(p: np.ndarray, u: np.ndarray, ctrl: np.ndarray):
    """Maior distancia ponto-curva e o indice onde ela ocorre."""
    d = np.array([bezier_ponto(ctrl, t) for t in u]) - p
    dist = np.hypot(d[:, 0], d[:, 1])
    k = int(np.argmax(dist))
    return float(dist[k]), k


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def ajustar(pontos, tol: float = 1.0, fechado: bool = False,
            max_iter: int = MAX_ITER) -> list[np.ndarray]:
    """Ajusta uma cadeia de Bezier cubicas aos pontos.

    Parameters
    ----------
    pontos : (N,2)
    tol : desvio maximo aceito, na unidade dos pontos (px)
    fechado : se o contorno fecha, o primeiro ponto e repetido no fim e as
        tangentes das pontas sao calculadas com wrap-around, o que evita
        um bico artificial na emenda
    max_iter : iteracoes de Newton-Raphson por trecho

    Returns
    -------
    lista de arrays (4,2): os pontos de controle de cada Bezier, em ordem.
    """
    p = np.asarray(pontos, dtype=float)
    # remove pontos repetidos consecutivos — quebram a parametrizacao
    if len(p) > 1:
        manter = np.concatenate([[True], (np.abs(np.diff(p, axis=0)).sum(1) > _EPS)])
        p = p[manter]
    if len(p) < 2:
        return []

    if fechado:
        if np.hypot(*(p[-1] - p[0])) > _EPS:
            p = np.vstack([p, p[0]])
        t1 = _norm(p[1] - p[0])
        t2 = _norm(p[-2] - p[-1])
        # emenda suave: media das tangentes que chegam e saem do ponto inicial
        med = _norm(t1 - t2)
        if np.hypot(*med) > _EPS:
            t1, t2 = med, -med
    else:
        t1 = _tangente_esq(p, 0)
        t2 = _tangente_dir(p, len(p) - 1)

    saida: list[np.ndarray] = []
    _fit(p, 0, len(p) - 1, t1, t2, tol, max_iter, saida, 0)
    return saida


def _fit(p, first, last, t1, t2, tol, max_iter, saida, prof):
    n = last - first + 1
    sub = p[first:last + 1]

    if n == 2:
        dist = float(np.hypot(*(p[last] - p[first]))) / 3.0
        saida.append(np.array([p[first], p[first] + t1 * dist,
                               p[last] + t2 * dist, p[last]]))
        return

    u = _parametrizar(sub)
    ctrl = _gerar_bezier(sub, u, t1, t2)
    err, k = _erro_max(sub, u, ctrl)

    if err < tol:
        saida.append(ctrl)
        return

    # SEMPRE refina o parametro antes de quebrar.
    # No artigo original de Schneider o erro e QUADRATICO, e a condicao de
    # entrada era 'err < error*error'. Aqui o erro e distancia real, e usar
    # aquela condicao literal faz o refinamento nunca rodar: com tol=0.2 ela
    # vira '0.75 < 0.04'. O resultado eram 173 Bezier num circulo que precisa
    # de 4. Refinar sempre custa poucas iteracoes e resolve.
    for _ in range(max_iter):
        u = _reparametrizar(sub, u, ctrl)
        novo = _gerar_bezier(sub, u, t1, t2)
        e2, k2 = _erro_max(sub, u, novo)
        if e2 < err:                 # so aceita se melhorou
            ctrl, err, k = novo, e2, k2
        if err < tol:
            saida.append(ctrl)
            return

    if prof > 24:                      # trava de seguranca
        saida.append(ctrl)
        return

    split = first + k
    if split <= first:
        split = first + 1
    if split >= last:
        split = last - 1

    tc = _tangente_centro(p, split)
    _fit(p, first, split, t1, tc, tol, max_iter, saida, prof + 1)
    _fit(p, split, last, -tc, t2, tol, max_iter, saida, prof + 1)


# ---------------------------------------------------------------------------
# saida para DXF
# ---------------------------------------------------------------------------
def para_path(curvas, transformar=None):
    """Monta um ezdxf.path.Path com as Bezier cubicas.

    O Path e a ponte natural: ezdxf.path.to_splines_and_polylines() o
    converte em SPLINE de grau 3, sem perda.
    """
    from ezdxf.path import Path

    if not curvas:
        return None
    tf = transformar or (lambda xy: (float(xy[0]), float(xy[1])))
    caminho = Path(tf(curvas[0][0]))
    for c in curvas:
        caminho.curve4_to(tf(c[3]), tf(c[1]), tf(c[2]))
    return caminho


def erro_real(pontos, curvas, amostras: int = 24) -> float:
    """Desvio maximo dos pontos originais a cadeia de Bezier ajustada.

    Mede ponto-a-SEGMENTO da curva densamente amostrada, nao ponto-a-vertice:
    a distancia ao vertice mais proximo superestima grosseiramente em trecho
    longo, e foi assim que uma medicao anterior deste projeto deu 153 px
    quando o erro real era fracao de pixel.
    """
    if not curvas:
        return float("inf")
    dense = []
    for c in curvas:
        for t in np.linspace(0, 1, amostras, endpoint=False):
            dense.append(bezier_ponto(c, float(t)))
    dense.append(curvas[-1][3])
    poly = np.array(dense)

    p = np.asarray(pontos, dtype=float)
    a, b = poly[:-1], poly[1:]
    ab = b - a
    L2 = (ab ** 2).sum(1)
    L2[L2 == 0] = _EPS
    pior = 0.0
    for pt in p:
        t = np.clip(((pt - a) * ab).sum(1) / L2, 0.0, 1.0)
        proj = a + t[:, None] * ab
        pior = max(pior, float(np.hypot(*(pt - proj).T).min()))
    return pior
