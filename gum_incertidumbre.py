"""
=============================================================
  METROMECANICA — Módulo GUM de Incertidumbre
  Presupuesto completo + Welch-Satterthwaite + factor k
  Referencia: JCGM 100:2008 (GUM), PC-008 INACAL (2ª Ed. 2009)
  Integración: metromecanica_v6.py
=============================================================
  USO:
    from gum_incertidumbre import calcular_incertidumbre_gum, tabla_t_student

  INTEGRACIÓN EN generar_pdf_ensayo():
    Llamar a calcular_incertidumbre_gum(ensayo, rho_prom)
    y pasar el resultado a _seccion_gum_pdf(story, resultado_gum, ...)
=============================================================
"""

import math


# ════════════════════════════════════════════════════════════
#  TABLA t-STUDENT (GUM Tabla G.2 — nivel de confianza 95,45%)
#  Fuente: JCGM 100:2008 Tabla G.2, interpolación lineal entre puntos
# ════════════════════════════════════════════════════════════

_T_STUDENT_95 = {
    1: 12.706, 2: 4.303,  3: 3.182,  4: 2.776,  5: 2.571,
    6: 2.447,  7: 2.365,  8: 2.306,  9: 2.262,  10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,  15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,  20: 2.086,
    25: 2.060, 30: 2.042, 40: 2.021, 50: 2.009,  60: 2.000,
    80: 1.990, 100: 1.984, 120: 1.980, 200: 1.972, 500: 1.965,
}
_T_INF = 1.960  # t para ν → ∞


def tabla_t_student() -> list[dict]:
    """
    Retorna la tabla t-Student completa para nivel de confianza 95%.
    Formato: [{"nu": int, "t95": float, "nota": str}, ...]
    Apta para imprimir en PDF o mostrar en consola.
    """
    filas = []
    for nu, t in sorted(_T_STUDENT_95.items()):
        nota = ""
        if nu == 1:
            nota = "muy bajo — evitar"
        elif nu <= 4:
            nota = "bajo — k > 2 seguro"
        elif nu <= 9:
            nota = "moderado — verificar k"
        elif nu <= 29:
            nota = "aceptable"
        else:
            nota = "k = 2,00 justificado"
        filas.append({"nu": nu, "t95": round(t, 3), "nota": nota})
    filas.append({"nu": "∞", "t95": _T_INF, "nota": "k = 1,960 exacto"})
    return filas


def _get_t95(nu: float) -> float:
    """Interpola t₀.₉₅ para un ν_eff dado."""
    if not math.isfinite(nu) or nu >= 500:
        return _T_INF
    nu = max(1.0, nu)
    keys = sorted(_T_STUDENT_95.keys())
    # Búsqueda del intervalo
    for i in range(len(keys) - 1):
        k0, k1 = keys[i], keys[i + 1]
        if k0 <= nu <= k1:
            t0, t1 = _T_STUDENT_95[k0], _T_STUDENT_95[k1]
            frac = (nu - k0) / (k1 - k0)
            return round(t0 + frac * (t1 - t0), 4)
    if nu >= keys[-1]:
        return _T_INF
    return _T_STUDENT_95[keys[0]]


# ════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════

def calcular_incertidumbre_gum(
    ensayo: dict,
    rho_prom: float | None = None,
    n_series: int = 1,
    s_series: float | None = None,
    u_patron_expandida: float = 0.060,
    d_resolucion: float = 1.0,
    nu_patron: float = float('inf'),
    rho_pesa: float = 8000.0,
    rho_patron: float = 8000.0,
    nominal_g: float = 20000.0,
) -> dict:
    """
    Calcula el presupuesto completo de incertidumbre GUM (JCGM 100:2008)
    para un ensayo ABA de calibración de pesas M2 según PC-008 INACAL.

    Parámetros
    ----------
    ensayo          : dict del ensayo (salida de _registrar_aba en v6)
    rho_prom        : densidad promedio del aire [kg/m³] (CIPM-2007)
                      Si None, se usa 1.2 kg/m³ (valor de referencia OIML)
    n_series        : número de series ABA realizadas (para u_A tipo A)
                      Si el ensayo tiene una sola medición, n=1 y u_A = s_aprox
    s_series        : desviación estándar de la serie [g]
                      Si None, se estima como 0,3 g (típico WANT GT-30000TR)
    u_patron_expandida : U del patrón (k=2) en gramos, del certificado
    d_resolucion    : división de escala de la balanza [g]  (1 g para WANT)
    nu_patron       : grados de libertad del patrón
                      (∞ para patrón calibrado con certificado acreditado)
    rho_pesa        : densidad de la pesa a calibrar [kg/m³]
    rho_patron      : densidad del patrón [kg/m³]
    nominal_g       : valor nominal de la pesa [g]

    Retorna
    -------
    dict con claves:
        fuentes         : list[dict] — cada fuente con u_i, ci, vi, contribucion
        u_c             : incertidumbre estándar combinada [g]
        u_c_mg          : ídem en [mg]
        nu_eff          : grados de libertad efectivos (Welch-Satterthwaite)
        t95             : t-Student para nu_eff al 95%
        k               : factor de cobertura adoptado
        k_justificacion : texto explicativo
        U               : incertidumbre expandida [g]
        U_mg            : ídem en [mg]
        nivel_confianza : '~95 %'
        texto_certificado : bloque listo para copiar al certificado
        conforme_criterio : bool — U ≤ MPE/3 (criterio ISO 17025)
        ratio_U_MPE     : U / MPE
        MPE_mg          : error máximo permisible M2 para el nominal dado
    """

    # ── 1. Parámetros del ensayo ─────────────────────────────
    nom = ensayo.get('nominal', nominal_g)
    dcr = ensayo.get('dcr', 0.0)        # corrección del patrón [g]

    # ── 2. Corrección por empuje de aire (boyancy) ─────────
    rho_a = (rho_prom / 1000.0) if rho_prom else 0.0012  # → g/cm³
    rho_x = rho_pesa   / 1000.0                           # → g/cm³
    rho_r = rho_patron / 1000.0                           # → g/cm³
    delta_mB = nom * rho_a * (1.0 / rho_x - 1.0 / rho_r)

    # ── 3. Fuentes de incertidumbre ──────────────────────────

    # 3a. Tipo A — Repetibilidad
    if s_series is None:
        s_series = 0.300   # g — estimación conservadora para WANT d=1g
    if n_series < 1:
        n_series = 1
    u_A  = s_series / math.sqrt(n_series) if n_series > 1 else s_series
    nu_A = n_series - 1 if n_series > 1 else 1

    # 3b. Tipo B — Patrón (distribución normal, k=2 declarado)
    u_R  = u_patron_expandida / 2.0
    nu_R = nu_patron   # ∞ para patrón con certificado acreditado

    # 3c. Tipo B — Resolución (distribución rectangular)
    #     u_res = d / (2√3)   ← GUM sección 4.3.7
    u_res  = d_resolucion / (2.0 * math.sqrt(3.0))
    nu_res = float('inf')

    # 3d. Tipo B — Empuje de aire (distribución rectangular)
    #     u_B = |δmB| / √3
    u_B  = abs(delta_mB) / math.sqrt(3.0)
    nu_B = float('inf')

    fuentes = [
        {
            "nombre":     "Repetibilidad — u_A = s / √n",
            "simbolo":    "u_A",
            "tipo":       "A",
            "dist":       "Normal",
            "formula":    f"s={s_series:.4f} g / √{n_series}",
            "u_i_g":      u_A,
            "u_i_mg":     round(u_A * 1000, 4),
            "ci":         1.0,
            "c_i_u_i_mg": round(u_A * 1000, 4),
            "nu_i":       nu_A,
        },
        {
            "nombre":     "Incertidumbre del patrón — u_R = U_pat / 2",
            "simbolo":    "u_R",
            "tipo":       "B",
            "dist":       "Normal",
            "formula":    f"U_pat={u_patron_expandida:.4f} g / 2",
            "u_i_g":      u_R,
            "u_i_mg":     round(u_R * 1000, 4),
            "ci":         1.0,
            "c_i_u_i_mg": round(u_R * 1000, 4),
            "nu_i":       nu_R,
        },
        {
            "nombre":     "Resolución de la balanza — u_res = d / (2√3)",
            "simbolo":    "u_res",
            "tipo":       "B",
            "dist":       "Rectangular",
            "formula":    f"d={d_resolucion} g / (2√3)",
            "u_i_g":      u_res,
            "u_i_mg":     round(u_res * 1000, 4),
            "ci":         1.0,
            "c_i_u_i_mg": round(u_res * 1000, 4),
            "nu_i":       float('inf'),
        },
        {
            "nombre":     "Empuje del aire — u_B = |δmB| / √3",
            "simbolo":    "u_B",
            "tipo":       "B",
            "dist":       "Rectangular",
            "formula":    f"δmB={delta_mB:.6f} g / √3",
            "u_i_g":      u_B,
            "u_i_mg":     round(u_B * 1000, 4),
            "ci":         1.0,
            "c_i_u_i_mg": round(u_B * 1000, 4),
            "nu_i":       float('inf'),
        },
    ]

    # ── 4. Incertidumbre combinada ───────────────────────────
    u_c2 = sum((f["ci"] * f["u_i_g"]) ** 2 for f in fuentes)
    u_c  = math.sqrt(u_c2)

    # Contribución porcentual de cada fuente (en varianza)
    for f in fuentes:
        contrib2 = (f["ci"] * f["u_i_g"]) ** 2
        f["contrib_pct"] = round(contrib2 / u_c2 * 100, 1) if u_c2 > 0 else 0.0

    # ── 5. Welch-Satterthwaite (GUM Ec. E.3) ────────────────
    #   ν_eff = u_c⁴ / Σ [ (c_i · u_i)⁴ / ν_i ]
    #   Solo los ν finitos contribuyen al denominador.
    denom_ws = 0.0
    for f in fuentes:
        vi = f["nu_i"]
        if math.isfinite(vi) and vi > 0:
            denom_ws += ((f["ci"] * f["u_i_g"]) ** 4) / vi

    if denom_ws > 0:
        nu_eff = u_c2 ** 2 / denom_ws
        nu_eff = min(nu_eff, 10000.0)
    else:
        nu_eff = float('inf')   # todos los ν son ∞

    # ── 6. Factor de cobertura k ─────────────────────────────
    t95   = _get_t95(nu_eff)
    # GUM §G.6.4: si t₀.₉₅(ν_eff) > 2,00 → adoptar k = t₀.₉₅(ν_eff)
    # Si t₀.₉₅ ≤ 2,00 → adoptar k = 2,00 por convenio (nivel de confianza ~95,45%)
    k = max(t95, 2.00)
    k = round(k, 2)

    if not math.isfinite(nu_eff) or nu_eff >= 200:
        k_just = (
            f"ν_eff = ∞  (dominado por fuentes tipo B con distribución conocida). "
            f"t₀,₉₅(∞) = {_T_INF:.3f}. Se adopta k = 2,00 por convenio GUM §G.6.4."
        )
    elif nu_eff >= 30:
        k_just = (
            f"ν_eff = {nu_eff:.0f} ≥ 30. t₀,₉₅(ν_eff) = {t95:.3f} ≈ 2,00. "
            f"k = 2,00 está plenamente justificado."
        )
    elif nu_eff >= 10:
        k_just = (
            f"ν_eff = {nu_eff:.1f}. t₀,₉₅(ν_eff) = {t95:.3f} > 2,00. "
            f"Se adopta k = {k:.2f}. Para justificar k = 2,00 aumentar n a ≥ 10 series."
        )
    else:
        k_just = (
            f"ATENCIÓN: ν_eff = {nu_eff:.1f} bajo. t₀,₉₅(ν_eff) = {t95:.3f}. "
            f"k = {k:.2f} obligatorio. Aumentar n de series ABA."
        )

    U    = k * u_c
    U_mg = round(U * 1000, 1)
    u_c_mg = round(u_c * 1000, 1)

    # ── 7. MPE y criterio conformidad ────────────────────────
    _EMP_M2_LOCAL = {
        5000000:800000, 2000000:300000, 1000000:160000,
        500000:80000,   200000:30000,   100000:16000,
        50000:8000,     20000:3000,     10000:1600,
        5000:800,       2000:300,       1000:160,
        500:80,         200:30,         100:16,
        50:10,          20:8,           10:6, 5:5, 2:4, 1:3,
    }
    MPE_mg = None
    for k_emp in sorted(_EMP_M2_LOCAL.keys()):
        if abs(k_emp - nom) < 0.001:
            MPE_mg = _EMP_M2_LOCAL[k_emp]; break
    if MPE_mg is None:
        for k_emp in sorted(_EMP_M2_LOCAL.keys()):
            if k_emp >= nom:
                MPE_mg = _EMP_M2_LOCAL[k_emp]; break
    if MPE_mg is None:
        MPE_mg = 1000

    ratio_U_MPE      = round(U_mg / MPE_mg, 4) if MPE_mg else None
    conforme_criterio = (U_mg <= MPE_mg / 3) if MPE_mg else None

    # ── 8. Texto listo para certificado ─────────────────────
    nu_txt = f"{nu_eff:.0f}" if math.isfinite(nu_eff) else "∞"
    texto_cert = (
        f"La incertidumbre de medición se determinó conforme a la GUM (JCGM 100:2008) "
        f"y al procedimiento PC-008 (INACAL, 2.ª Ed. 2009).\n\n"
        f"Fuentes evaluadas:\n"
        f"  (A) Repetibilidad instrumental: u_A = {u_A*1000:.1f} mg  "
        f"(s = {s_series*1000:.1f} mg, n = {n_series} series, ν = {nu_A})\n"
        f"  (B) Incertidumbre del patrón (cert. acreditado): u_R = {u_R*1000:.1f} mg  "
        f"(U_pat = {u_patron_expandida*1000:.1f} mg, k=2, ν = {'∞' if not math.isfinite(nu_R) else str(int(nu_R))})\n"
        f"  (B) Resolución de la balanza: u_res = {u_res*1000:.2f} mg  "
        f"(d = {d_resolucion:.1f} g, dist. rectangular, ν = ∞)\n"
        f"  (B) Corrección por empuje del aire: u_B = {u_B*1000:.2f} mg  "
        f"(δmB = {delta_mB*1000:.2f} mg, dist. rectangular, ν = ∞)\n\n"
        f"Incertidumbre estándar combinada:   u_c = {u_c_mg:.1f} mg\n"
        f"Grados de libertad efectivos:       ν_eff = {nu_txt}  "
        f"(fórmula Welch-Satterthwaite, GUM Ec. E.3)\n"
        f"Factor de cobertura:                k = {k:.2f}  "
        f"(t₀,₉₅; ν_eff; nivel de confianza ≈ 95 %)\n"
        f"Incertidumbre expandida:            U = {U_mg:.0f} mg  (k = {k:.2f})\n\n"
        f"Justificación de k:\n{k_just}"
    )

    return {
        "fuentes":            fuentes,
        "delta_mB_g":         round(delta_mB, 6),
        "delta_mB_mg":        round(delta_mB * 1000, 4),
        "u_c":                round(u_c, 6),
        "u_c_mg":             u_c_mg,
        "nu_eff":             round(nu_eff, 1) if math.isfinite(nu_eff) else float('inf'),
        "t95":                t95,
        "k":                  k,
        "k_justificacion":    k_just,
        "U":                  round(U, 6),
        "U_mg":               U_mg,
        "nivel_confianza":    "~95 %",
        "texto_certificado":  texto_cert,
        "conforme_criterio":  conforme_criterio,
        "ratio_U_MPE":        ratio_U_MPE,
        "MPE_mg":             MPE_mg,
    }


# ════════════════════════════════════════════════════════════
#  SECCIÓN PDF — llamar desde generar_pdf_ensayo() del v6
# ════════════════════════════════════════════════════════════

def _seccion_gum_pdf(story, gum: dict, st_sec, st_nota, colors_mod, cm_mod):
    """
    Agrega la sección 'PRESUPUESTO DE INCERTIDUMBRE GUM' al story de ReportLab.
    Insertar en generar_pdf_ensayo() entre sección 5 (OIML) y sección 6 (Trazabilidad).

    Parámetros
    ----------
    story     : lista de flowables ReportLab (se modifica in-place)
    gum       : dict retornado por calcular_incertidumbre_gum()
    st_sec    : ParagraphStyle para encabezados de sección (del v6)
    st_nota   : ParagraphStyle para notas pie de tabla (del v6)
    colors_mod: módulo reportlab.lib.colors importado en generar_pdf_ensayo
    cm_mod    : unidad cm de reportlab.lib.units
    """
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT

    colors = colors_mod
    cm     = cm_mod

    story.append(Paragraph("6. PRESUPUESTO DE INCERTIDUMBRE — GUM (JCGM 100:2008)", st_sec))

    # ── Tabla fuentes ────────────────────────────────────────
    cabecera = [
        "Fuente de incertidumbre", "Tipo", "Dist.", "u_i (mg)", "c_i", "c_i·u_i (mg)", "ν_i"
    ]
    filas = [cabecera]
    for f in gum["fuentes"]:
        nu_str = "∞" if not math.isfinite(f["nu_i"]) else str(int(f["nu_i"]))
        filas.append([
            f["nombre"],
            f["tipo"],
            f["dist"][:4],
            str(f["u_i_mg"]).replace(".", ","),
            "1,0",
            str(f["c_i_u_i_mg"]).replace(".", ","),
            nu_str,
        ])

    # Fila totales
    k_str = str(gum["k"]).replace(".", ",")
    nu_eff_str = "∞" if not math.isfinite(gum["nu_eff"]) else f"{gum['nu_eff']:.0f}"
    filas.append([
        f"u_c combinada = {str(gum['u_c_mg']).replace('.',',')} mg  |  "
        f"ν_eff = {nu_eff_str}  |  "
        f"k = {k_str}  |  U = {str(gum['U_mg']).replace('.',',')} mg  (k={k_str}, ~95%)",
        "", "", "", "", "", ""
    ])

    col_ws = [6.5*cm, 0.8*cm, 1.0*cm, 1.5*cm, 0.8*cm, 2.0*cm, 0.9*cm]
    tbl = Table(filas, colWidths=col_ws)
    s = TableStyle([
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 7.5),
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',     (0,0), (-1,0),  colors.white),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
        ('ALIGN',         (0,0), (0,-1),  'LEFT'),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        # Fila total — span completo
        ('SPAN',          (0,-1), (-1,-1)),
        ('FONTNAME',      (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,-1), (-1,-1), 8),
        ('BACKGROUND',    (0,-1), (-1,-1), colors.HexColor('#dce6f7')),
        ('FONTCOLOR',     (0,-1), (-1,-1), colors.HexColor('#1a3a6b')),
    ])
    for i in range(1, len(filas) - 1):
        bg = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
        s.add('BACKGROUND', (0, i), (-1, i), bg)
    tbl.setStyle(s)
    story.append(tbl)
    story.append(Spacer(1, 0.15*cm))

    # ── Tabla Welch-Satterthwaite + k ────────────────────────
    nu_disp  = "∞" if not math.isfinite(gum["nu_eff"]) else f"{gum['nu_eff']:.1f}"
    conf_color_k = colors.HexColor('#d4edda') if gum["k"] <= 2.05 else colors.HexColor('#fff3cd')
    conf_color_u = colors.HexColor('#d4edda') if gum.get("conforme_criterio") else colors.HexColor('#f8d7da')

    k_tbl_data = [
        ["Parámetro", "Valor", "Referencia / Descripción"],
        ["ν_eff (Welch-Satterthwaite)",
         nu_disp,
         "GUM Ec. E.3: ν_eff = u_c⁴ / Σ[(c_i·u_i)⁴/ν_i]"],
        ["t₀,₉₅(ν_eff) — tabla t-Student",
         str(gum["t95"]).replace(".", ","),
         "GUM Tabla G.2 — nivel de confianza 95 %"],
        ["Factor de cobertura k adoptado",
         k_str,
         gum["k_justificacion"][:80] + ("…" if len(gum["k_justificacion"]) > 80 else "")],
        ["Incertidumbre expandida U",
         f"{str(gum['U_mg']).replace('.',',')} mg",
         f"U = k · u_c = {k_str} × {str(gum['u_c_mg']).replace('.',',')} mg"],
        ["U / MPE (criterio ISO 17025)",
         f"{str(gum.get('ratio_U_MPE','')).replace('.',',')}",
         f"MPE M2 = {gum.get('MPE_mg','—')} mg  |  "
         f"{'CUMPLE — U ≤ MPE/3' if gum.get('conforme_criterio') else 'NO CUMPLE — revisar patrón'}"],
    ]
    k_tbl = Table(k_tbl_data, colWidths=[4.5*cm, 2.0*cm, 11.0*cm])
    ks = TableStyle([
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 7.5),
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',     (0,0), (-1,0),  colors.white),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('ALIGN',         (1,0), (1,-1),  'CENTER'),
        # Fila k — color según validez
        ('BACKGROUND',    (0,3), (-1,3),  conf_color_k),
        ('FONTNAME',      (0,3), (-1,3),  'Helvetica-Bold'),
        # Fila U criterio — color conformidad
        ('BACKGROUND',    (0,5), (-1,5),  conf_color_u),
        ('FONTNAME',      (0,5), (-1,5),  'Helvetica-Bold'),
    ])
    for i in [1, 2, 4]:
        bg = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
        ks.add('BACKGROUND', (0, i), (-1, i), bg)
    k_tbl.setStyle(ks)
    story.append(k_tbl)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "Nota: Los grados de libertad de las fuentes tipo B (patrón certificado, "
        "resolución y empuje del aire) se consideran ∞ conforme al GUM §G.4.2, "
        "dado que sus distribuciones de probabilidad son bien conocidas.",
        st_nota))
    story.append(Spacer(1, 0.2*cm))


# ════════════════════════════════════════════════════════════
#  INTEGRACIÓN EN v6 — instrucciones de patch
# ════════════════════════════════════════════════════════════
"""
PASO 1 — Importar al inicio de metromecanica_v6.py:
─────────────────────────────────────────────────────
    from gum_incertidumbre import calcular_incertidumbre_gum, _seccion_gum_pdf

PASO 2 — En generar_pdf_ensayo(), después de calcular rho_prom (línea ~817):
──────────────────────────────────────────────────────────────────────────────
    gum_resultado = calcular_incertidumbre_gum(
        ensayo         = ensayo,
        rho_prom       = rho_prom,          # ya calculado en la sección 5
        n_series       = 1,                 # 1 = una medición ABA única (típico v6)
        s_series       = 0.300,             # g — desv. estándar típica WANT GT-30000TR
        u_patron_expandida = abs(ensayo.get('dcr', 0)) * 2 + 0.060,  # ajustar con cert.
        d_resolucion   = 2 if 'RADWAG' in ensayo.get('balanza','') else 1,
        rho_pesa       = 8000.0,            # kg/m³ — actualizar según material
        rho_patron     = 8000.0,
        nominal_g      = ensayo.get('nominal', 20000.0),
    )

PASO 3 — En generar_pdf_ensayo(), reemplazar la numeración de sección 6 existente:
────────────────────────────────────────────────────────────────────────────────────
    # Después de story.append(oiml_t) y story.append(Spacer(...))
    _seccion_gum_pdf(story, gum_resultado, st_sec, st_nota, colors, cm)
    n_sec = 8   # (era 7, la trazabilidad pasa a ser sección 8)

PASO 4 — Ajustar referencias:
──────────────────────────────
    story.append(Paragraph(f"{n_sec}. TRAZABILIDAD ...", st_sec))
    story.append(Paragraph(f"{n_sec+1}. FIRMAS", st_sec))
"""


# ════════════════════════════════════════════════════════════
#  DEMO / TEST STANDALONE
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":

    # Simulación de un ensayo real con WANT GT-30000TR
    ensayo_prueba = {
        "nominal":    20000.0,
        "dcr":        0.200,    # g — corrección del patrón
        "balanza":    "WANT GT-30000TR",
        "id_pesa":    "PW-20K-001",
        "patron_id":  "PAT-20K-M1",
        "n_cert":     "CERT-001-2025",
        "operador":   "Gabriel Ramirez",
    }

    # Tabla t-Student
    print("\n" + "="*60)
    print("  TABLA t-STUDENT — GUM Tabla G.2 — Nivel de confianza 95%")
    print("="*60)
    print(f"  {'ν_eff':>8}  {'t₀.₉₅':>7}  {'Observación':<35}")
    print("  " + "-"*55)
    for row in tabla_t_student():
        nu_str = str(row['nu']) if isinstance(row['nu'], int) else row['nu']
        print(f"  {nu_str:>8}  {row['t95']:>7.3f}  {row['nota']:<35}")

    # Cálculo GUM
    print("\n" + "="*60)
    print("  PRESUPUESTO GUM — WANT GT-30000TR — 20 kg M2")
    print("="*60)

    resultado = calcular_incertidumbre_gum(
        ensayo             = ensayo_prueba,
        rho_prom           = 1.1839,   # kg/m³ — Lima a 1013 hPa, 20°C
        n_series           = 5,
        s_series           = 0.300,
        u_patron_expandida = 0.060,
        d_resolucion       = 1.0,
        nu_patron          = float('inf'),
        rho_pesa           = 7800.0,   # hierro fundido — peor caso boyancy
        rho_patron         = 8000.0,
        nominal_g          = 20000.0,
    )

    print(f"\n  Boyancy δmB       = {resultado['delta_mB_mg']:+.4f} mg")
    print(f"\n  {'Fuente':<40} {'Tipo':>4}  {'u_i (mg)':>9}  {'%':>5}  {'ν':>5}")
    print("  " + "-"*70)
    for f in resultado["fuentes"]:
        nu_s = "∞" if not math.isfinite(f["nu_i"]) else str(int(f["nu_i"]))
        print(f"  {f['nombre']:<40} {f['tipo']:>4}  "
              f"{f['u_i_mg']:>9.4f}  {f['contrib_pct']:>5.1f}%  {nu_s:>5}")

    print(f"\n  u_c = {resultado['u_c_mg']:.1f} mg")
    nu_disp2 = "∞" if not math.isfinite(resultado['nu_eff']) else f"{resultado['nu_eff']:.1f}"
    print(f"  ν_eff = {nu_disp2}")
    print(f"  t₀.₉₅(ν_eff) = {resultado['t95']:.3f}")
    print(f"  k = {resultado['k']:.2f}")
    print(f"  U = {resultado['U_mg']:.0f} mg")
    print(f"\n  Criterio U/MPE = {resultado['ratio_U_MPE']:.3f}  "
          f"({'CUMPLE' if resultado['conforme_criterio'] else 'NO CUMPLE'})")
    print(f"\n  JUSTIFICACIÓN k:\n  {resultado['k_justificacion']}")
    print(f"\n{'='*60}")
    print("  TEXTO PARA CERTIFICADO:")
    print("="*60)
    print(resultado["texto_certificado"])
