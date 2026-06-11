"""
============================================================
CALIBRACION MICROMETRO DE EXTERIORES — GUI PORTABLE
Metromecanica | PC-013 INDECOPI/INACAL | ISO/IEC 17025
DIN 863-1 | GUM
============================================================
"""

import json, os, sys, math, datetime, threading, traceback
import urllib.request, urllib.error
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, Image, HRFlowable, PageBreak,
                                 KeepTogether)
from reportlab.lib import colors
import hashlib

# ============================================================
# SUPABASE
# ============================================================
SUPABASE_URL = "https://ndcjjksaiecsuzperrhp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5kY2pqa3NhaWVjc3V6cGVycmhwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjU5OTE4MiwiZXhwIjoyMDg4MTc1MTgyfQ.pdgxsNk-33mBuKCI_wxhYHxvz2h8POmBvhR69Tqsw6o"

def _supabase_upsert(tabla, datos):
    url = "{}/rest/v1/{}".format(SUPABASE_URL, tabla)
    body = json.dumps(datos).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type":  "application/json",
            "Prefer":        "resolution=merge-duplicates,return=representation",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, resp.read().decode()
    except urllib.error.HTTPError as e:
        return False, e.read().decode()
    except Exception as e:
        return False, str(e)

def guardar_registro_json(ruta, registro):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

def _supabase_insert(tabla, datos):
    url = "{}/rest/v1/{}".format(SUPABASE_URL, tabla)
    body = json.dumps(datos).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type":  "application/json",
            "Prefer":        "return=representation",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, resp.read().decode()
    except urllib.error.HTTPError as e:
        return False, e.read().decode()
    except Exception as e:
        return False, str(e)

def _supabase_get(tabla, filtro=None):
    url = "{}/rest/v1/{}?select=*".format(SUPABASE_URL, tabla)
    if filtro:
        url += "&" + filtro
    req = urllib.request.Request(url, method="GET",
        headers={"apikey": SUPABASE_KEY,
                 "Authorization": "Bearer " + SUPABASE_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return []

def _supabase_delete(tabla, id_val):
    url = "{}/rest/v1/{}?id=eq.{}".format(SUPABASE_URL, tabla, id_val)
    req = urllib.request.Request(url, method="DELETE",
        headers={"apikey": SUPABASE_KEY,
                 "Authorization": "Bearer " + SUPABASE_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except:
        return False

# ============================================================
# CONFIG
# ============================================================
CONFIG = {
    "razon_social"    : "METROMECANICA INGENIERIA Y METROLOGIA S.A.C.",
    "area_laboratorio": "Laboratorio de Longitud y Angulo",
    "lugar_calibracion": "Laboratorio de Longitud y Angulo - METROMECANICA",
    "norma_base"      : "PC-013 INACAL / ISO 3611:2010 / DIN 863-1",
    "metodo_texto"    : (
        "Calibracion por comparacion directa con bloques patron de longitud "
        "segun PC-013 INACAL (ex INDECOPI), ISO 3611:2010 y DIN 863-1."
    ),
    "temp_referencia" : 20.0,
    "alpha_BP"        : 11.5e-6,
    "Delta_alpha_BP"  : 1.0e-6,
    "alpha_mic"       : 11.5e-6,
    "Delta_alpha_mic" : 1.0e-6,
    "factor_cobertura": 2,
    "nivel_confianza" : "95 %",
    "n_lecturas"      : 5,
    # EMP segun DIN 863-1 (µm) por rango en mm
    "EMP_DIN863": {
        (0,   25):  4,
        (25,  50):  4,
        (50,  75):  5,
        (75, 100):  5,
        (100,125):  6,
        (125,150):  6,
        (150,175):  7,
        (175,200):  7,
        (200,225):  8,
        (225,250):  8,
        (250,275):  9,
        (275,300):  9,
        (300,325): 10,
        (325,350): 10,
        (350,375): 11,
        (375,400): 11,
        (400,425): 12,
        (425,450): 12,
        (450,475): 13,
        (475,500): 13,
    },
}

def emp_din863(L_mm):
    for (lo, hi), val in CONFIG["EMP_DIN863"].items():
        if lo <= L_mm <= hi:
            return val
    return None

# ============================================================
# PDF ESTILOS / COLORES
# ============================================================
W = A4[0]; H = A4[1]
NEGRO  = colors.black
GRIS   = colors.HexColor('#555555')
GRIS_C = colors.HexColor('#CCCCCC')
GRIS_F = colors.HexColor('#F0F0F0')

def _es():
    return {
        "tit_cert": ParagraphStyle('tc', fontName='Helvetica', fontSize=14, leading=18, alignment=TA_CENTER),
        "tit_pag" : ParagraphStyle('tp', fontName='Helvetica', fontSize=10, leading=13, alignment=TA_CENTER),
        "sub_pag" : ParagraphStyle('sp', fontName='Helvetica', fontSize=8,  leading=11, alignment=TA_CENTER, textColor=GRIS),
        "pag_r"   : ParagraphStyle('pr', fontName='Helvetica', fontSize=8,  leading=10, alignment=TA_RIGHT,  textColor=GRIS),
        "nor"     : ParagraphStyle('no', fontName='Helvetica', fontSize=7.5, leading=11, alignment=TA_LEFT),
        "nor_b"   : ParagraphStyle('nb', fontName='Helvetica-Bold', fontSize=8, leading=11, alignment=TA_LEFT),
        "nor_r"   : ParagraphStyle('nr', fontName='Helvetica', fontSize=8, leading=11, alignment=TA_RIGHT),
        "cen"     : ParagraphStyle('cn', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_CENTER),
        "lbl"     : ParagraphStyle('lb', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_LEFT, textColor=GRIS),
        "val"     : ParagraphStyle('vl', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_LEFT),
        "decl"    : ParagraphStyle('dc', fontName='Helvetica', fontSize=6.5, leading=9,  alignment=TA_JUSTIFY, textColor=GRIS),
        "nota_pie": ParagraphStyle('np', fontName='Helvetica', fontSize=7,   leading=9.5, alignment=TA_LEFT, textColor=GRIS),
        "unc"     : ParagraphStyle('uc', fontName='Helvetica-Bold', fontSize=8, leading=12, alignment=TA_LEFT),
        "fin_doc" : ParagraphStyle('fd', fontName='Helvetica', fontSize=8, leading=11, alignment=TA_CENTER, textColor=GRIS),
        "sec"     : ParagraphStyle('sc', fontName='Helvetica-Bold', fontSize=8, leading=11, spaceBefore=2),
    }

def _ts():
    return TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7.5),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),('GRID',(0,0),(-1,-1),0.4,NEGRO),
        ('BACKGROUND',(0,0),(-1,0),GRIS_F),('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2.5),
        ('BOTTOMPADDING',(0,0),(-1,-1),2.5),('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
    ])

# ============================================================
# CONVERSION DE UNIDADES
# ============================================================
MM_POR_PULGADA = 25.4

def mm_a_pulg(mm): return mm / MM_POR_PULGADA
def pulg_a_mm(pulg): return pulg * MM_POR_PULGADA

# ============================================================
# FORMATO DECIMAL CON COMA (norma metrologica peruana)
# ============================================================
def fc(valor, decimales=3):
    """Formatea un numero usando coma como separador decimal."""
    fmt = "{:.Xf}".replace("X", str(decimales))
    return fmt.format(float(valor)).replace(".", ",")

# ============================================================
# MATEMATICAS PC-013
# ============================================================
def _media(v): return sum(v)/len(v)
def _s(v):
    m=_media(v)
    return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1)) if len(v)>1 else 0.
def _rect(a): return a/math.sqrt(3)
def _norm(U,k): return U/k
def _uc(cs): return math.sqrt(sum(c**2 for c in cs))

def calcular_todo(mediciones, inst, patron, planitud, paralelismo,
                  c_ini, c_fin, caras="planas"):
    """
    mediciones: lista de dicts con nominal, LBP, T_bloque, lecturas[5], T_mic
    inst: {resolucion, tipo, m, rango_min, rango_max}
    patron: {certificado, vigencia, U, k}
    planitud: {tope_fijo_bandas, tope_fijo_desv_um, tope_movil_bandas, tope_movil_desv_um}
    paralelismo: lista de {valor_paralela_mm, bandas, desv_um}
    """
    cfg = CONFIG
    T_ref = cfg["temp_referencia"]
    alpha_mic = cfg["alpha_mic"]
    alpha_BP  = cfg["alpha_BP"]
    k2 = cfg["factor_cobertura"]

    # u termico
    T_vals = ([c_ini["temperatura"], c_fin["temperatura"]] +
              [d["T_bloque"] for d in mediciones] + [d["T_mic"] for d in mediciones])
    dT_max = max(abs(t - T_ref) for t in T_vals)
    u_dT   = dT_max / math.sqrt(3)
    u_dalpha = math.sqrt(_rect(cfg["Delta_alpha_BP"])**2 + _rect(cfg["Delta_alpha_mic"])**2)

    # u patron
    u_BP_cal = _norm(patron["U"], patron["k"])

    # u planitud caras (promedio de ambos topes)
    delta_plan = max(planitud["tope_fijo_desv_um"], planitud["tope_movil_desv_um"])
    u_plan = delta_plan / (2 * math.sqrt(3))

    # u paralelismo (maximo desv)
    if paralelismo:
        delta_paral = max(p["desv_um"] for p in paralelismo)
    else:
        delta_paral = 0.0
    u_paral = delta_paral / (2 * math.sqrt(3))

    # u division de escala
    d = inst["resolucion"] * 1000  # en um
    m = inst["m"]
    u_div = (d / m) / math.sqrt(3)

    resultados = []
    for dp in mediciones:
        nom  = dp["nominal"]
        LBP  = dp["LBP"]
        lecs = dp["lecturas"]
        T_B  = dp["T_bloque"]
        T_M  = dp["T_mic"]
        med  = _media(lecs)
        n    = len(lecs)

        # u tipo A (repetibilidad)
        s    = _s(lecs)
        u_A  = s * 1000 / math.sqrt(n)   # en um

        # u patron (calibracion + deriva)
        u_BP_der = (0.05e-3 + 0.5e-6 * LBP) * 1000  # en um
        u_BP_tot = math.sqrt((u_BP_cal * 1000)**2 + u_BP_der**2)

        # correccion termica
        dT_i = T_M - T_ref
        dT_b = T_B - T_ref
        error_mm = (med * (1 + alpha_mic * dT_i) - LBP * (1 + alpha_BP * dT_b))
        error_um = error_mm * 1000

        # u termico
        u_term = math.sqrt(
            (LBP * 1e-3 * alpha_BP  * u_dT * 1e6)**2 +
            (LBP * 1e-3 * dT_i * u_dalpha * 1e6)**2
        )

        # uc total (en um)
        uc_um = _uc([u_A, u_BP_tot, u_plan, u_paral, u_div, u_term])
        U_um  = k2 * uc_um
        U_mm  = U_um / 1000

        emp = emp_din863(nom)

        resultados.append({
            "nominal":    nom,
            "LBP":        LBP,
            "T_bloque":   T_B,
            "T_mic":      T_M,
            "lecturas":   lecs,
            "media":      med,
            "desv_um":    s * 1000,
            "error_mm":   error_mm,
            "error_um":   error_um,
            "u_A_um":     u_A,
            "u_BP_um":    u_BP_tot,
            "u_plan_um":  u_plan,
            "u_paral_um": u_paral,
            "u_div_um":   u_div,
            "u_term_um":  u_term,
            "uc_um":      uc_um,
            "U_um":       U_um,
            "U_mm":       U_mm,
            "EMP_um":     emp,
            "cumple":     (abs(error_um) <= emp) if emp else None,
        })

    # alcance del error f_max
    f_max = max(abs(r["error_um"]) for r in resultados)

    comps = {
        "u_A_max":    max(r["u_A_um"]    for r in resultados),
        "u_BP_max":   max(r["u_BP_um"]   for r in resultados),
        "u_plan":     u_plan,
        "u_paral":    u_paral,
        "u_div":      u_div,
        "u_term_max": max(r["u_term_um"] for r in resultados),
        "U_max":      max(r["U_um"]      for r in resultados),
        "f_max":      f_max,
    }
    return resultados, comps

# ============================================================
# GRAFICO
# ============================================================
def _grafico(resultados, ruta):
    x = [r["LBP"]     for r in resultados]
    y = [r["error_um"] for r in resultados]
    emp_vals = [r["EMP_um"] for r in resultados if r["EMP_um"]]

    fig, ax = plt.subplots(figsize=(6.5, 3.4), dpi=160)
    fig.patch.set_facecolor('white'); ax.set_facecolor('white')
    ax.plot(x, y, color='black', linewidth=1.2, marker='D', markersize=4.5,
            markerfacecolor='black', markeredgecolor='black', label='Error')
    ax.axhline(0, color='black', linewidth=0.6)

    if emp_vals:
        emp_val = emp_vals[0]
        ax.axhline( emp_val, color='gray', linewidth=0.8, linestyle='--', label='+EMP')
        ax.axhline(-emp_val, color='gray', linewidth=0.8, linestyle='--', label='-EMP')

    ax.set_xlabel('Valor Nominal  ( mm )', fontsize=8)
    ax.set_ylabel('Error  ( µm )', fontsize=8)
    ax.set_title('Error de Indicacion del Micrometro de Exteriores', fontsize=9, fontweight='bold')
    ax.tick_params(labelsize=7.5)
    ax.grid(True, linestyle='-', linewidth=0.3, color='#AAAAAA', alpha=0.7)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend(fontsize=7, loc='upper left')
    for sp in ax.spines.values():
        sp.set_edgecolor('black'); sp.set_linewidth(0.6)
    plt.tight_layout(pad=0.8)
    plt.savefig(ruta, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close()

# ============================================================
# PDF — 3 PAGINAS (mismo formato que vernier)
# ============================================================
def convertir_resultados(resultados, unidad):
    """Convierte resultados de mm a pulgadas si se requiere."""
    if unidad == "mm":
        return resultados
    conv = []
    for r in resultados:
        rc = dict(r)
        rc["nominal"]  = mm_a_pulg(r["nominal"])
        rc["LBP"]      = mm_a_pulg(r["LBP"])
        rc["media"]    = mm_a_pulg(r["media"])
        rc["lecturas"] = [mm_a_pulg(l) for l in r["lecturas"]]
        # Error y U se convierten de um a micropulgadas (uin) o a pulgadas
        rc["error_um"] = r["error_um"] / MM_POR_PULGADA  # ahora en uin (micropulgadas)
        rc["U_um"]     = r["U_um"]     / MM_POR_PULGADA
        rc["error_mm"] = mm_a_pulg(r["error_mm"])
        rc["U_mm"]     = mm_a_pulg(r["U_mm"])
        conv.append(rc)
    return conv

def generar_pdf(cfg_eq, inst, patron, planitud, paralelismo,
                c_ini, c_fin, resultados, comps,
                ruta_pdf, ruta_img, fecha_cal,
                total_pags=3, responsable_nombre="", responsable_reg="",
                proxima_calibracion="A solicitud del usuario"):

    es  = _es()
    ahora = datetime.datetime.now()
    cod = cfg_eq.get("codigo_certificado","") or cfg_eq.get("codigo","") or "---"
    if not cod or cod == "---":
        cod = "---"
    pag = [0]

    def on_page(canvas, doc):
        pag[0] += 1
        canvas.saveState()
        canvas.setFont("Helvetica", 7); canvas.setFillColor(GRIS)
        canvas.drawCentredString(W/2, 10*mm,
            "Certificado de Calibracion  {}  |  Pag. {} de {}".format(cod, pag[0], total_pags))
        canvas.restoreState()

    doc = SimpleDocTemplate(ruta_pdf, pagesize=A4,
        rightMargin=50*mm, leftMargin=50*mm,
        topMargin=50*mm,   bottomMargin=50*mm,
        title="Certificado de Calibracion {}".format(cod))

    s = []; sep = lambda n=2: s.append(Spacer(1, n*mm))
    hr  = lambda: s.append(HRFlowable(width="100%", thickness=0.5, color=GRIS_C))
    hr1 = lambda: s.append(HRFlowable(width="100%", thickness=0.3, color=GRIS_C))

    cli = cfg_eq.get("cliente", {})

    def sec(num, titulo):
        return Paragraph("<b>{}.-  {}</b>".format(num, titulo), es["sec"])

    def lbl_val(label, valor):
        return Table([[Paragraph(label, es["lbl"]), Paragraph(":  {}".format(valor), es["val"])]],
            colWidths=[42*mm, 68*mm],
            style=TableStyle([("TOPPADDING",(0,0),(-1,-1),1),
                              ("BOTTOMPADDING",(0,0),(-1,-1),1),
                              ("VALIGN",(0,0),(-1,-1),"TOP")]))

    u = inst.get("unidad","mm")
    # Convertir resultados a la unidad seleccionada
    resultados = convertir_resultados(resultados, u)
    if u == "pulg":
        uni_lbl  = "in"
        uni_err  = "µin"
        dec_val  = 5   # decimales para valores en pulgadas
        dec_err  = 4   # decimales para errores
        rango_str = fc(inst.get("rango_min_orig", mm_a_pulg(inst["rango_min"])),3)+'" a '+fc(inst.get("rango_max_orig", mm_a_pulg(inst["rango_max"])),3)+'"'
        res_str   = fc(inst.get("resolucion_orig", mm_a_pulg(inst["resolucion"])),5)+'"'
    else:
        uni_lbl  = "mm"
        uni_err  = "µm"
        dec_val  = 4
        dec_err  = 2
        rango_str = fc(inst["rango_min"],1)+" mm a "+fc(inst["rango_max"],1)+" mm"
        res_str   = fc(inst["resolucion"],2)+" mm"

    # ── PAGINA 1 ─────────────────────────────────────────────
    s.append(Paragraph("Certificado de Calibracion<br/><b>{}</b>".format(cod), es["tit_cert"]))
    sep(1)

    t = Table([
        [Paragraph("<b>Orden de Trabajo :</b>  {}  -  {}".format(
            cfg_eq.get('ot','---'), CONFIG['area_laboratorio']), es["nor"]),
         Paragraph("<b>Fecha de Emision :</b>  {}".format(ahora.strftime('%Y-%m-%d')), es["nor_r"])],
        [Paragraph("<b>N Guia :</b>  {}".format(cfg_eq.get('guia','---')), es["nor"]),
         Paragraph("<b>Pagina 1 de {}</b>".format(total_pags), es["nor_r"])],
    ], colWidths=[100*mm, 60*mm])
    t.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    s.append(t); sep(2); hr(); sep(2)

    col_izq = []
    col_izq.append(sec("1","Informacion del solicitante")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(lbl_val("Nombre o Razon Social", "<b>{}</b>".format(cli.get('nombre','---'))))
    col_izq.append(lbl_val("Direccion", cli.get("direccion","---")))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("2","Informacion del Equipo")); col_izq.append(Spacer(1,1*mm))
    for label, valor in [
        ("Descripcion",       "Micrometro de Exteriores"),
        ("Marca",             cfg_eq.get("marca","---")),
        ("Modelo",            cfg_eq.get("modelo","---")),
        ("N° Serie",          cfg_eq.get("serie","---")),
        ("Identificacion",    "{}  (*)".format(cfg_eq.get("codigo_interno","---"))),
        ("Alcance",           rango_str),
        ("V. Division Escala", res_str),
        ("Tipo de Indicacion", inst["tipo"]),
    ]:
        col_izq.append(lbl_val(label, valor))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("3","Fecha de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}  (**)".format(fecha_cal), es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("4","Lugar de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}".format(CONFIG['lugar_calibracion']), es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("5","Metodo de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}".format(CONFIG['metodo_texto']), es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("6","Condiciones Ambientales")); col_izq.append(Spacer(1,1*mm))
    t_cond = Table([
        [Paragraph("<b>Temperatura</b>", es["cen"]),
         Paragraph("<b>Humedad</b>", es["cen"]),
         Paragraph("<b>Presion</b>", es["cen"])],
        [Paragraph(fc(c_ini['temperatura'],1)+" C  a  "+fc(c_fin['temperatura'],1)+" C", es["cen"]),
         Paragraph(fc(c_ini['humedad'],1)+" %HR  a  "+fc(c_fin['humedad'],1)+" %HR", es["cen"]),
         Paragraph(fc(float(str(c_ini.get("presion",1013))),0)+" mbar", es["cen"])],
    ], colWidths=[40*mm, 40*mm, 30*mm])
    t_cond.setStyle(TableStyle([
        ("FONTSIZE",(0,0),(-1,-1),7.5),("GRID",(0,0),(-1,-1),0.4,NEGRO),
        ("BACKGROUND",(0,0),(-1,0),GRIS_F),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    col_izq.append(t_cond)
    col_izq.append(Spacer(1,15*mm))

    decls = [
        "Los resultados son validos solo para el equipo calibrado en el momento de la medicion.",
        "Este certificado es trazable a patrones nacionales e internacionales (SI).",
        "No podra ser reproducido parcialmente sin autorizacion escrita de {}.".format(CONFIG['razon_social']),
        "No es valido sin la firma del responsable tecnico.",
        "Se recomienda calibrar los equipos a intervalos apropiados.",
    ]
    col_der = []
    for txt in decls:
        col_der.append(Paragraph(txt, es["decl"]))
        col_der.append(Spacer(1,3*mm))

    t_dos = Table([[col_izq, col_der]], colWidths=[115*mm, 45*mm])
    t_dos.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    s.append(t_dos)

    # ── PAGINA 2 ─────────────────────────────────────────────
    s.append(PageBreak())
    s.append(Paragraph("Certificado de Calibracion  <b>{}</b>".format(cod), es["tit_pag"]))
    sep(1)
    s.append(Paragraph(CONFIG["area_laboratorio"], es["sub_pag"]))
    s.append(Paragraph("Pagina 2 de {}".format(total_pags), es["pag_r"]))
    sep(2); hr1(); sep(2)

    # 7. Trazabilidad
    s.append(sec("7","Trazabilidad")); sep(1)
    t_traz = Table(
        [[Paragraph("<b>Vigencia</b>", es["cen"]),
          Paragraph("<b>Equipo o Instrumento Patron</b>", es["cen"]),
          Paragraph("<b>Certificado de Calibracion</b>", es["cen"])],
         [Paragraph(str(patron.get("vigencia","---")), es["cen"]),
          Paragraph(str(patron.get("instrumento","Bloques patron de longitud (gauge blocks)")), es["cen"]),
          Paragraph(str(patron.get("certificado","---")), es["cen"])]],
        colWidths=[30*mm, 80*mm, 50*mm])
    t_traz.setStyle(_ts())
    s.append(KeepTogether(t_traz)); sep(3)

    # 8. Resultados de Calibracion
    s.append(sec("8","Resultados de Calibracion")); sep(1)
    s.append(Paragraph(
        "Temperatura del micrometro — Inicio: "+fc(c_ini["temperatura"],1)+" C   Final: "+fc(c_fin["temperatura"],1)+" C  |  Unidad: {}".format(uni_lbl.upper()),
        es["nor_b"])); sep(1)

    # Tabla resultados — Bloques | VP | Prom. Indicacion | Error | U | EMP | Cumple
    enc = [
        Paragraph("<b>Bloques\nUtilizados\n(mm)</b>", es["cen"]),
        Paragraph("<b>Valor Patron\nVP (mm)</b>", es["cen"]),
        Paragraph("<b>Promedio Indicacion\nMicrometro Exteriores\n(mm)</b>", es["cen"]),
        Paragraph("<b>Error\n(µm)</b>", es["cen"]),
        Paragraph("<b>Incertidumbre\nU (µm)</b>", es["cen"]),
    ]
    filas = [enc]
    for r in resultados:
        fila = [
            Paragraph(fc(r['nominal'],   dec_val), es['cen']),
            Paragraph(fc(r['LBP'],       dec_val), es['cen']),
            Paragraph(fc(r['media'],     dec_val), es['cen']),
            Paragraph(fc(r['error_um'],  dec_err), es['cen']),
            Paragraph(fc(r['U_um'],      dec_err), es['cen']),
        ]
        filas.append(fila)

    # fila f_max
    filas.append([
        Paragraph("<b>Alcance del error de indicacion (f_max)</b>", es["nor_b"]),
        Paragraph(""), Paragraph(""),
        Paragraph("<b>"+fc(comps["f_max"],2)+" µm</b>", es["cen"]),
        Paragraph(""),
    ])

    cw = [28*mm, 32*mm, 55*mm, 28*mm, 28*mm]
    t_res = Table(filas, colWidths=cw)
    t_res.setStyle(_ts())
    t_res.setStyle(TableStyle([
        ('SPAN', (0,-1),(2,-1)),
        ('ALIGN',(0,-1),(2,-1),'LEFT'),
        ('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),
        ('BACKGROUND',(0,-1),(-1,-1),GRIS_F),
    ]))
    s.append(KeepTogether(t_res)); sep(1)
    # EMP debajo de la tabla
    emp_rango = emp_din863(inst["rango_max"])
    if emp_rango:
        if inst.get("unidad","mm") == "pulg":
            emp_pulg = emp_rango / MM_POR_PULGADA / 1000
            rmax_orig = inst.get("rango_max_orig", mm_a_pulg(inst["rango_max"]))
            emp_txt = 'Error Maximo Permisible (EMP) DIN 863-1 para alcance {} in: <b>+/- {:.6f} in</b>'.format(
                fc(rmax_orig,3), emp_pulg)
        else:
            emp_txt = 'Error Maximo Permisible (EMP) DIN 863-1 para alcance {} mm: <b>+/- {} µm</b>'.format(
                fc(inst["rango_max"],0), fc(emp_rango,0))
        s.append(Paragraph(emp_txt, es["nor_b"])); sep(1)
    s.append(Paragraph(
        "VP = Valor patron corregido por certificado.  "
        "U = Incertidumbre expandida k={}, {}.".format(
            CONFIG["factor_cobertura"], CONFIG["nivel_confianza"]),
        es["nota_pie"])); sep(3)

    s.append(KeepTogether(Image(ruta_img, width=130*mm, height=65*mm))); sep(2)
    hr1()

    # ── PAGINA 3 ─────────────────────────────────────────────
    s.append(PageBreak())
    s.append(Paragraph("Certificado de Calibracion  <b>{}</b>".format(cod), es["tit_pag"]))
    sep(1)
    s.append(Paragraph(CONFIG["area_laboratorio"], es["sub_pag"]))
    s.append(Paragraph("Pagina 3 de {}".format(total_pags), es["pag_r"]))
    sep(2); hr1(); sep(2)

    # Incertidumbre expandida — solo valor final
    s.append(sec("11","Incertidumbre de Medicion")); sep(1)
    t_unc = Table([
        [Paragraph("<b>Incertidumbre Expandida  U  (k = {})</b>".format(CONFIG["factor_cobertura"]), es["nor_b"]),
         Paragraph("<b>+/- {} µm</b>".format(fc(comps["U_max"],2)), es["cen"])],
    ], colWidths=[110*mm, 50*mm])
    t_unc.setStyle(TableStyle([
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('GRID',(0,0),(-1,-1),0.5,NEGRO),
        ('BACKGROUND',(0,0),(-1,-1),GRIS_F),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
    ]))
    s.append(KeepTogether(t_unc)); sep(1)
    s.append(Paragraph(
        "La incertidumbre expandida se obtuvo con factor k={}, "
        "probabilidad de cobertura 95%, distribucion normal.".format(CONFIG["factor_cobertura"]),
        es["nor"])); sep(3)

    s.append(sec("12","Observaciones y Recomendaciones")); sep(1)
    obs = [
        "(*) Identificacion hallada en la superficie del equipo.",
        "(**) Fecha en que se realizo la calibracion.",
        "Alcance del error de indicacion (f_max): {:.1f} um".format(comps["f_max"]),
        "Se coloco etiqueta 'CALIBRADO' con codigo {}.".format(cod),
        "Proxima calibracion:  {}".format(proxima_calibracion),
    ]
    obs_extra = cfg_eq.get("datos_adicionales","").strip()
    if obs_extra:
        obs.insert(2, obs_extra)
    for o in obs:
        s.append(Paragraph("*  {}".format(o), es["nor"])); sep(1)

    sep(4); hr(); sep(2)
    s.append(Paragraph("Fin del Documento", es["fin_doc"]))

    doc.build(s, onFirstPage=on_page, onLaterPages=on_page)

# ============================================================
# GUI
# ============================================================
BG="1a1a2e"; BG="#1a1a2e"; BG2="#16213e"; BG3="#0f3460"
ACC="#00d4aa"; TEXT="#e0e0e0"; TEXT2="#aaaaaa"
FONT=("Segoe UI",9); FONTB=("Segoe UI",9,"bold")

def _entry(parent, var, width=12):
    return tk.Entry(parent, textvariable=var, width=width,
                    bg=BG2, fg=TEXT, insertbackground=ACC,
                    relief="flat", font=FONT,
                    highlightthickness=1, highlightbackground=BG3,
                    highlightcolor=ACC)

def _sec(parent, titulo):
    f = tk.Frame(parent, bg=BG)
    tk.Label(f, text="  "+titulo, bg=BG3, fg=ACC, font=FONTB,
             anchor="w", padx=6, pady=3).pack(fill="x", pady=(8,3))
    return f

class NumField(tk.Frame):
    def __init__(self, parent, label, default="0", width=10, **kw):
        super().__init__(parent, bg=BG, **kw)
        tk.Label(self, text=label, bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0,4))
        default_str = str(default).replace(".", ",")
        self.var = tk.StringVar(value=default_str)
        e = _entry(self, self.var, width)
        e.pack(side="left")
        def on_key(event):
            if event.char == '.':
                pos = e.index(tk.INSERT)
                cur = self.var.get()
                self.var.set(cur[:pos] + ',' + cur[pos:])
                e.icursor(pos + 1)
                return "break"
        e.bind("<Key>", on_key)
    def get(self):
        v = self.var.get().replace(",",".")
        return float(v) if v.strip() else 0.0
    def set(self, v): self.var.set(str(v).replace(".", ","))

class StrField(tk.Frame):
    def __init__(self, parent, label, default="", width=22, **kw):
        super().__init__(parent, bg=BG, **kw)
        tk.Label(self, text=label, bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0,4))
        self.var = tk.StringVar(value=default)
        _entry(self, self.var, width).pack(side="left", fill="x", expand=True)
    def get(self): return self.var.get().strip()
    def set(self, v): self.var.set(str(v))

class MicApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calibracion Micrometro Exteriores - Metromecanica")
        self.configure(bg=BG)
        self.geometry("960x720")
        self.cfg_eq = {}
        self._campos_meds = []
        self._campos_paral = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG3, pady=6); hdr.pack(fill="x")
        tk.Label(hdr, text="CALIBRACION MICROMETRO DE EXTERIORES",
                 bg=BG3, fg=ACC, font=("Segoe UI",13,"bold")).pack(side="left", padx=14)
        tk.Label(hdr, text="PC-013 INACAL | DIN 863-1 | ISO/IEC 17025",
                 bg=BG3, fg=TEXT2, font=FONT).pack(side="left")

        style = ttk.Style(); style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=TEXT2, padding=[12,5], font=FONT)
        style.map("TNotebook.Tab", background=[("selected",BG3)], foreground=[("selected",ACC)])

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=6, pady=6)

        tabs = [
            ("📂 JSON / Equipo",        self._tab_json),
            ("🔧 Instrumento",          self._tab_instrumento),
            ("🌡 Condiciones",          self._tab_condiciones),
            ("📐 Planitud/Paralelismo", self._tab_planitud),
            ("📏 Mediciones",           self._tab_mediciones),
            ("✅ Generar PDF",          self._tab_generar),
            ("⚙ Patrones",             self._tab_patrones),
        ]
        for titulo, build in tabs:
            frame = tk.Frame(nb, bg=BG)
            build(frame)
            nb.add(frame, text=titulo)

    # ── TAB JSON ─────────────────────────────────────────────
    def _tab_json(self, f):
        # Busqueda por OT desde Supabase
        hdr = tk.Frame(f, bg=BG3, pady=6); hdr.pack(fill="x", padx=10, pady=(8,0))
        tk.Label(hdr, text="  Buscar equipo pendiente por N° OT (Supabase)",
                 bg=BG3, fg=ACC, font=FONTB).pack(side="left")

        row_ot = tk.Frame(f, bg=BG); row_ot.pack(fill="x", padx=14, pady=6)
        self._ot_buscar = tk.StringVar()
        _entry(row_ot, self._ot_buscar, 20).pack(side="left", padx=(0,6))
        tk.Button(row_ot, text="Buscar en Supabase", command=self._buscar_por_ot,
                  bg=ACC, fg="#000", font=FONTB, relief="flat", padx=10, pady=4, cursor="hand2"
                  ).pack(side="left", padx=(0,8))

        self._ot_var = tk.StringVar()
        self._ot_combo = ttk.Combobox(row_ot, textvariable=self._ot_var,
                                       width=38, state="readonly", font=FONT)
        self._ot_combo.pack(side="left", padx=(0,6))
        self._ot_combo.bind("<<ComboboxSelected>>", self._on_equipo_sel)
        tk.Button(row_ot, text="Cargar", command=lambda: self._on_equipo_sel(None),
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="left")

        self._pendientes_lista = []

        tk.Frame(f, bg=BG3, height=1).pack(fill="x", padx=10, pady=4)

        hdr2 = tk.Frame(f, bg=BG); hdr2.pack(fill="x", padx=14)
        tk.Label(hdr2, text="O cargar desde archivo JSON local:",
                 bg=BG, fg=TEXT2, font=("Segoe UI",8,"italic")).pack(side="left")

        row = tk.Frame(f, bg=BG); row.pack(fill="x", padx=14, pady=4)
        self.json_path = tk.StringVar()
        _entry(row, self.json_path, 40).pack(side="left", padx=(0,8))
        tk.Button(row, text="Seleccionar JSON...", command=self._cargar_json,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")

        self.lbl_json = tk.Label(f, text="Sin datos cargados", bg=BG, fg=TEXT2, font=FONT)
        self.lbl_json.pack(anchor="w", padx=14)

        s2 = _sec(f, "Datos del equipo"); s2.pack(fill="x", padx=10)
        grid = tk.Frame(s2, bg=BG); grid.pack(fill="x", padx=8, pady=4)
        self._ev = {}
        campos = [
            ("eq_ot","N° OT:",30),("eq_cert","Cod. Certificado:",22),
            ("eq_desc","Descripcion:",42),("eq_marca","Marca:",18),
            ("eq_modelo","Modelo:",18),("eq_serie","N° Serie:",18),
            ("eq_codigo","ID/Codigo:",18),("eq_guia","N° Guia:",18),
            ("eq_cliente","Cliente:",40),("eq_ruc","RUC:",16),
            ("eq_dir","Direccion:",50),
        ]
        for i,(key,lbl,w) in enumerate(campos):
            r,c = divmod(i,2)
            frm = tk.Frame(grid, bg=BG)
            frm.grid(row=r, column=c, sticky="w", padx=6, pady=2)
            tk.Label(frm, text=lbl, bg=BG, fg=TEXT2, font=FONT, width=17, anchor="e").pack(side="left")
            var = tk.StringVar(); self._ev[key] = var
            _entry(frm, var, w).pack(side="left")

    def _buscar_por_ot(self):
        ot = self._ot_buscar.get().strip()
        if not ot:
            messagebox.showwarning("Aviso", "Ingresa un numero de OT"); return
        self.lbl_json.config(text="Buscando en Supabase...", fg=TEXT2)
        self.update_idletasks()
        try:
            data = _supabase_get("services",
                "ot_number=eq.{}&select=ot_number,client,ruc,contacto,correo,direccion_fiscal,ingresos".format(ot))
            if not data:
                self.lbl_json.config(text="No se encontro la OT: {}".format(ot), fg="#f59e0b")
                self._ot_combo["values"] = []
                return
            svc = data[0]
            ingresos = svc.get("ingresos") or []
            if isinstance(ingresos, str):
                import json as _json
                ingresos = _json.loads(ingresos)
            if not ingresos:
                self.lbl_json.config(text="Sin equipos en OT: {}".format(ot), fg="#f59e0b")
                return
            self._svc_data = svc
            self._pendientes_lista = ingresos
            opciones = ["{} | {} {} | Serie: {}".format(
                eq.get("descripcion","---"),
                eq.get("marca",""),
                eq.get("modelo",""),
                eq.get("nro_serie","---")
            ) for eq in ingresos]
            self._ot_combo["values"] = opciones
            self._ot_combo.current(0)
            self._on_equipo_sel(None)
            self.lbl_json.config(
                text="{} equipo(s) en OT {}".format(len(ingresos), ot), fg=ACC)
        except Exception as e:
            self.lbl_json.config(text="Error: {}".format(str(e)[:60]), fg="#ef4444")

    def _on_equipo_sel(self, event):
        """Autocompleta campos desde JSON de services."""
        idx = self._ot_combo.current()
        if idx < 0 or idx >= len(self._pendientes_lista): return
        eq = self._pendientes_lista[idx]
        svc = getattr(self, '_svc_data', {})
        self._ev["eq_ot"].set(svc.get("ot_number",""))
        self._ev["eq_cliente"].set(svc.get("client",""))
        self._ev["eq_ruc"].set(svc.get("ruc",""))
        self._ev["eq_dir"].set(svc.get("direccion_fiscal",""))
        self._ev["eq_cert"].set(eq.get("codigo_certificado",""))
        self._ev["eq_desc"].set(eq.get("descripcion",""))
        self._ev["eq_marca"].set(eq.get("marca",""))
        self._ev["eq_modelo"].set(eq.get("modelo",""))
        self._ev["eq_serie"].set(eq.get("nro_serie",""))
        self._ev["eq_codigo"].set(eq.get("id_equipo",""))
        self._ev["eq_guia"].set(eq.get("nro_guia",""))
        fecha = eq.get("fecha_asignacion","") or eq.get("fecha_ingreso","")
        if fecha and hasattr(self, 'fecha_cal'):
            self.fecha_cal.set(fecha)
        self._pendiente_id = str(eq.get("id",""))
        cert = eq.get("codigo_certificado","Sin codigo")
        self.lbl_json.config(
            text="Cargado: {} | Cert: {}".format(eq.get("descripcion",""), cert), fg=ACC)

    def _marcar_pendiente_completado(self, codigo_cert):
        if not hasattr(self, "_pendiente_id") or not self._pendiente_id: return
        url = "{}/rest/v1/calibraciones_pendientes?id=eq.{}".format(SUPABASE_URL, self._pendiente_id)
        body = json.dumps({"estado":"completado","codigo_certificado":codigo_cert}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PATCH",
            headers={"apikey":SUPABASE_KEY,"Authorization":"Bearer "+SUPABASE_KEY,
                     "Content-Type":"application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except:
            pass

    def _cargar_json(self):
        path = filedialog.askopenfilename(
            title="Seleccionar JSON",
            filetypes=[("JSON","*.json"),("Todos","*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8") as fp:
                self.cfg_eq = json.load(fp)
            self.json_path.set(path)
            eq  = self.cfg_eq.get("equipo", self.cfg_eq)
            cli = self.cfg_eq.get("cliente", {})
            self._ev["eq_ot"].set(self.cfg_eq.get("ot_number",""))
            self._ev["eq_cert"].set(eq.get("codigo_certificado",""))
            self._ev["eq_desc"].set(eq.get("descripcion",""))
            self._ev["eq_marca"].set(eq.get("marca",""))
            self._ev["eq_modelo"].set(eq.get("modelo",""))
            self._ev["eq_serie"].set(eq.get("nro_serie",""))
            self._ev["eq_codigo"].set(eq.get("id_equipo",""))
            self._ev["eq_guia"].set(eq.get("nro_guia",""))
            self._ev["eq_cliente"].set(self.cfg_eq.get("client","") or cli.get("nombre",""))
            self._ev["eq_ruc"].set(self.cfg_eq.get("ruc","") or cli.get("ruc",""))
            self._ev["eq_dir"].set(self.cfg_eq.get("direccion_fiscal","") or cli.get("direccion",""))
            self.lbl_json.config(text="OK: "+os.path.basename(path), fg=ACC)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── TAB INSTRUMENTO ───────────────────────────────────────
    def _tab_instrumento(self, f):
        s = _sec(f,"Parametros del micrometro"); s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        # Selector de unidad
        tk.Label(frm, text="Unidad de medicion:", bg=BG, fg=TEXT2, font=FONT).pack(anchor="w",pady=(0,2))
        self.inst_unidad = tk.StringVar(value="mm")
        row_u = tk.Frame(frm, bg=BG); row_u.pack(anchor="w")
        for v,t in [("mm","Milimetros (mm)"),("pulg","Pulgadas (in)")]:
            tk.Radiobutton(row_u, text=t, variable=self.inst_unidad, value=v,
                           bg=BG, fg=TEXT, selectcolor=BG3, activebackground=BG,
                           font=FONT, command=self._actualizar_unidad).pack(side="left", padx=(0,12))

        self.inst_res_lbl = tk.Label(frm, text="V. Division de Escala (mm):", bg=BG, fg=TEXT2, font=FONT)
        self.inst_res_lbl.pack(anchor="w", pady=(6,0))
        self.inst_res = NumField(frm,"","0,01",width=10)
        self.inst_res.pack(anchor="w", pady=2)

        tk.Label(frm, text="Tipo de Indicacion:", bg=BG, fg=TEXT2, font=FONT).pack(anchor="w",pady=(6,0))
        self.inst_tipo = tk.StringVar(value="Analogica")
        for v in ["Analogica","Digital"]:
            tk.Radiobutton(frm, text=v, variable=self.inst_tipo, value=v,
                           bg=BG, fg=TEXT, selectcolor=BG3, activebackground=BG,
                           font=FONT).pack(anchor="w")

        self.inst_m = NumField(frm,"N° subdivisiones m (analogico):","5",width=6)
        self.inst_m.pack(anchor="w", pady=2)

        tk.Label(frm, text="Tipo de caras:", bg=BG, fg=TEXT2, font=FONT).pack(anchor="w",pady=(6,0))
        self.inst_caras = tk.StringVar(value="planas")
        for v,t in [("planas","Plana - Plana"),("esferica","Plana - Esferica")]:
            tk.Radiobutton(frm, text=t, variable=self.inst_caras, value=v,
                           bg=BG, fg=TEXT, selectcolor=BG3, activebackground=BG,
                           font=FONT).pack(anchor="w")

        s2 = _sec(f,"Rango de calibracion"); s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=6)
        self.rango_min_lbl = tk.StringVar(value="Rango minimo (mm):")
        self.rango_max_lbl = tk.StringVar(value="Rango maximo (mm):")
        self.rango_min = NumField(frm2,"Rango minimo (mm):","0",width=10)
        self.rango_min.pack(anchor="w", pady=2)
        self.rango_max = NumField(frm2,"Rango maximo (mm):","25",width=10)
        self.rango_max.pack(anchor="w", pady=2)

        s3 = _sec(f,"Bloque patron (desde Supabase)"); s3.pack(fill="x", padx=10)
        frm3 = tk.Frame(s3, bg=BG); frm3.pack(fill="x", padx=8, pady=6)

        self._patrones_lista = []
        self._patron_sel = tk.StringVar()

        row_sel = tk.Frame(frm3, bg=BG); row_sel.pack(fill="x", pady=2)
        tk.Label(row_sel, text="Seleccionar patron:", bg=BG, fg=TEXT2, font=FONT, width=20, anchor="w").pack(side="left")
        self._combo_patron = ttk.Combobox(row_sel, textvariable=self._patron_sel,
                                           width=40, state="readonly", font=FONT)
        self._combo_patron.pack(side="left", padx=(0,6))
        self._combo_patron.bind("<<ComboboxSelected>>", self._on_patron_sel)
        self._patron_sel.trace_add("write", lambda *a: self._on_patron_sel(None))
        tk.Button(row_sel, text="↺ Recargar", command=self._cargar_patrones,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=6, cursor="hand2"
                  ).pack(side="left")

        self.pat_cert = StrField(frm3,"N° Certificado:",width=24)
        self.pat_cert.pack(anchor="w", pady=2)
        self.pat_vig  = StrField(frm3,"Vigencia:",width=14)
        self.pat_vig.pack(anchor="w", pady=2)
        self.pat_U    = NumField(frm3,"Incertidumbre U (mm):","0.0001",width=10)
        self.pat_U.pack(anchor="w", pady=2)
        self.pat_k    = NumField(frm3,"Factor k:","2",width=6)
        self.pat_k.pack(anchor="w", pady=2)

        self.lbl_pat = tk.Label(frm3, text="", bg=BG, fg=TEXT2, font=("Segoe UI",8,"italic"))
        self.lbl_pat.pack(anchor="w", pady=2)

        self._cargar_patrones()

    # ── TAB CONDICIONES ───────────────────────────────────────
    def _tab_condiciones(self, f):
        for momento in ["inicio","fin"]:
            s = _sec(f,"Condiciones al {}".format(momento))
            s.pack(fill="x", padx=10)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=5)
            t = NumField(frm,"Temperatura (C):","20.0",width=8); t.pack(anchor="w",pady=2)
            h = NumField(frm,"Humedad (%HR):","58.0",width=8); h.pack(anchor="w",pady=2)
            p = NumField(frm,"Presion (mbar):","1013",width=8); p.pack(anchor="w",pady=2)
            setattr(self,"cond_{}_t".format(momento),t)
            setattr(self,"cond_{}_h".format(momento),h)
            setattr(self,"cond_{}_p".format(momento),p)

    # ── TAB PLANITUD / PARALELISMO ────────────────────────────
    def _tab_planitud(self, f):
        s = _sec(f,"Planitud de las Caras de Medicion"); s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        tk.Label(frm, text="Tope fijo:", bg=BG, fg=ACC, font=FONTB).pack(anchor="w")
        self.plan_fijo_b = NumField(frm,"  N° Bandas de interferencia:","3",width=6)
        self.plan_fijo_b.pack(anchor="w", pady=1)
        self.plan_fijo_d = NumField(frm,"  Desviacion de planitud (µm):","0.9",width=8)
        self.plan_fijo_d.pack(anchor="w", pady=1)

        tk.Label(frm, text="Tope movil:", bg=BG, fg=ACC, font=FONTB).pack(anchor="w",pady=(8,0))
        self.plan_movil_b = NumField(frm,"  N° Bandas de interferencia:","4",width=6)
        self.plan_movil_b.pack(anchor="w", pady=1)
        self.plan_movil_d = NumField(frm,"  Desviacion de planitud (µm):","1.2",width=8)
        self.plan_movil_d.pack(anchor="w", pady=1)

        s2 = _sec(f,"Paralelismo de las Caras de Medicion"); s2.pack(fill="x", padx=10)

        tk.Button(f, text="+ Agregar punto de paralelismo",
                  command=self._agregar_paral,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, pady=3, cursor="hand2"
                  ).pack(pady=4)

        canvas = tk.Canvas(f, bg=BG, highlightthickness=0, height=180)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._paral_inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0,0), window=self._paral_inner, anchor="nw")
        self._paral_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        # Agregar 4 puntos por defecto
        for _ in range(4):
            self._agregar_paral()

    def _agregar_paral(self):
        i = len(self._campos_paral)
        frm = tk.Frame(self._paral_inner, bg=BG)
        frm.pack(anchor="w", padx=8, pady=2)
        tk.Label(frm, text="Punto {}:".format(i+1), bg=BG, fg=TEXT2, font=FONT, width=8).pack(side="left")
        vp  = NumField(frm,"VP (mm):","12.000",width=8); vp.pack(side="left",padx=4)
        ban = NumField(frm,"Bandas:","4",width=5); ban.pack(side="left",padx=4)
        dsv = NumField(frm,"Desv (µm):","1.2",width=6); dsv.pack(side="left",padx=4)
        tk.Button(frm, text="X", command=lambda f=frm,idx=i: self._eliminar_paral(f,idx),
                  bg=BG2, fg=TEXT2, font=FONT, relief="flat", padx=4, cursor="hand2"
                  ).pack(side="left",padx=4)
        self._campos_paral.append({"frm":frm,"vp":vp,"ban":ban,"dsv":dsv})

    def _eliminar_paral(self, frm, idx):
        frm.destroy()
        self._campos_paral = [p for p in self._campos_paral if p["frm"].winfo_exists()]

    # ── TAB MEDICIONES ────────────────────────────────────────
    def _tab_mediciones(self, f):
        tk.Button(f, text="Generar puntos de medicion",
                  command=self._gen_meds,
                  bg=ACC, fg="#000", font=FONTB, relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(pady=8)

        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._meds_inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0,0), window=self._meds_inner, anchor="nw")
        self._meds_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)),"units"))

    def _gen_meds(self):
        for w in self._meds_inner.winfo_children():
            w.destroy()
        self._campos_meds = []
        u = self.inst_unidad.get()
        uni = "in" if u == "pulg" else "mm"
        try:
            rmin_orig = self.rango_min.get()
            rmax_orig = self.rango_max.get()
        except:
            rmin_orig, rmax_orig = 0, 25
        # Convertir a mm para calculos internos
        if u == "pulg":
            rmin = pulg_a_mm(rmin_orig)
            rmax = pulg_a_mm(rmax_orig)
        else:
            rmin = rmin_orig
            rmax = rmax_orig
        if rmax <= rmin:
            rmax = rmin + (pulg_a_mm(1) if u == "pulg" else 25)
        paso = (rmax - rmin) / 10.0
        n = 11
        pts_mm = [round(rmin + i * paso, 5) for i in range(n)]
        dec = 4 if u == "pulg" else 3
        for i, nom_mm in enumerate(pts_mm):
            # Mostrar en la unidad seleccionada
            nom_disp = mm_a_pulg(nom_mm) if u == "pulg" else nom_mm
            s = _sec(self._meds_inner, "PUNTO {}  |  {:.{}f} {}".format(i+1, nom_disp, dec, uni))
            s.pack(fill="x", padx=6, pady=2)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=4)
            corr = NumField(frm, "Correccion bloque cert. ({}):".format(uni), "0,0", width=10)
            corr.pack(anchor="w", pady=1)
            tb = NumField(frm, "Temp. bloque (C):", "20,0", width=8)
            tb.pack(anchor="w", pady=1)
            lecs = []
            for j in range(CONFIG["n_lecturas"]):
                default = "{:.{}f}".format(nom_disp, dec).replace(".", ",")
                c = NumField(frm, "  Lectura X{} ({}):".format(j+1, uni), default, width=10)
                c.pack(anchor="w", pady=1)
                lecs.append(c)
            ti = NumField(frm, "Temp. micrometro (C):", "20,0", width=8)
            ti.pack(anchor="w", pady=1)
            # Guardar nominal en mm para calculos internos
            self._campos_meds.append({
                "nominal": nom_mm,
                "nominal_orig": nom_disp,
                "unidad": u,
                "corr": corr,
                "T_bloque": tb, "lecturas": lecs, "T_mic": ti
            })

    def _actualizar_unidad(self):
        """Actualiza labels cuando cambia la unidad."""
        u = self.inst_unidad.get()
        if u == "mm":
            self.inst_res_lbl.config(text="V. Division de Escala (mm):")
            self.inst_res.set("0,01")
            self.rango_min.set("0")
            self.rango_max.set("25")
        else:
            self.inst_res_lbl.config(text="V. Division de Escala (in):")
            self.inst_res.set("0,0001")
            self.rango_min.set("0")
            self.rango_max.set("1")

    def _cargar_patrones(self):
        try:
            self.lbl_pat.config(text="Cargando...", fg=TEXT2)
            self.update_idletasks()
            data = _supabase_get("patrones", "activo=eq.true&order=nombre.asc")
            self._patrones_lista = data if data else []
            nombres = ["{} | {} | U={} mm".format(
                p.get("nombre","---"), p.get("certificado","---"), p.get("u_mm","---")
            ) for p in self._patrones_lista]
            self._combo_patron["values"] = nombres
            if nombres:
                self._combo_patron.current(0)
                self._on_patron_sel(None)
                self.lbl_pat.config(text="{} patron(es) cargado(s)".format(len(nombres)), fg=ACC)
            else:
                self.lbl_pat.config(text="Sin patrones — agrega uno en pestana Patrones", fg="#f59e0b")
        except Exception as e:
            self.lbl_pat.config(text="Error: {}".format(str(e)[:50]), fg="#ef4444")

    def _on_patron_sel(self, event):
        idx = self._combo_patron.current()
        if idx < 0 or idx >= len(self._patrones_lista): return
        p = self._patrones_lista[idx]
        self.pat_cert.set(p.get("certificado",""))
        self.pat_vig.set(str(p.get("vigencia","")) if p.get("vigencia") else "")
        self.pat_U.set(p.get("u_mm", 0.0001))
        self.pat_k.set(p.get("k", 2))

    def _tab_patrones(self, f):
        """Pestana de gestion de patrones - requiere password admin."""
        self._admin_desbloqueado = False

        self._frm_admin_lock = tk.Frame(f, bg=BG)
        self._frm_admin_lock.pack(fill="both", expand=True)

        tk.Label(self._frm_admin_lock, text="", bg=BG).pack(pady=20)
        tk.Label(self._frm_admin_lock, text="Gestion de Patrones",
                 bg=BG, fg=ACC, font=("Segoe UI",13,"bold")).pack()
        tk.Label(self._frm_admin_lock,
                 text="Solo el Responsable Tecnico puede modificar los patrones.",
                 bg=BG, fg=TEXT2, font=FONT).pack(pady=4)

        frm_pwd = tk.Frame(self._frm_admin_lock, bg=BG); frm_pwd.pack(pady=12)
        tk.Label(frm_pwd, text="Password administrador:", bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0,6))
        self._admin_pwd = tk.StringVar()
        e = tk.Entry(frm_pwd, textvariable=self._admin_pwd, show="*", width=16,
                     bg=BG2, fg=TEXT, insertbackground=ACC, relief="flat", font=FONT,
                     highlightthickness=1, highlightbackground=BG3, highlightcolor=ACC)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self._verificar_admin())

        self._lbl_admin_err = tk.Label(self._frm_admin_lock, text="", bg=BG, fg="#ef4444", font=FONT)
        self._lbl_admin_err.pack()

        tk.Button(self._frm_admin_lock, text="Desbloquear",
                  command=self._verificar_admin,
                  bg=ACC, fg="#000", font=FONTB, relief="flat",
                  padx=14, pady=6, cursor="hand2").pack()

        self._frm_admin_panel = tk.Frame(f, bg=BG)

        hdr = tk.Frame(self._frm_admin_panel, bg=BG3, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Gestion de Patrones de Calibracion",
                 bg=BG3, fg=ACC, font=FONTB).pack(side="left")
        tk.Button(hdr, text="Cerrar sesion admin",
                  command=self._cerrar_admin,
                  bg=BG2, fg=TEXT2, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="right", padx=8)

        frm = tk.Frame(self._frm_admin_panel, bg=BG)
        frm.pack(fill="x", padx=14, pady=8)

        self._pnom  = StrField(frm, "Nombre:",        width=35); self._pnom.pack(anchor="w",  pady=2)
        self._pinst = StrField(frm, "Instrumento:",   width=35); self._pinst.pack(anchor="w", pady=2)
        self._pinst.set("Bloques patron de longitud (gauge blocks)")
        self._pcert = StrField(frm, "N° Certificado:", width=20); self._pcert.pack(anchor="w", pady=2)
        self._pvig  = StrField(frm, "Vigencia (aaaa-mm-dd):", width=14); self._pvig.pack(anchor="w", pady=2)
        self._pU    = NumField(frm, "U (mm):", "0.0001", width=10); self._pU.pack(anchor="w", pady=2)
        self._pk    = NumField(frm, "Factor k:", "2", width=6);     self._pk.pack(anchor="w", pady=2)

        tk.Button(frm, text="+ Agregar patron",
                  command=self._agregar_patron,
                  bg=ACC, fg="#000", font=FONTB, relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(anchor="w", pady=8)

        _sec(self._frm_admin_panel, "Patrones registrados").pack(fill="x", padx=10)

        canvas = tk.Canvas(self._frm_admin_panel, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self._frm_admin_panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._pat_inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0,0), window=self._pat_inner, anchor="nw")
        self._pat_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        tk.Button(self._frm_admin_panel, text="↺ Recargar lista",
                  command=self._refrescar_lista_patrones,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, pady=3, cursor="hand2"
                  ).pack(anchor="w", padx=14, pady=4)

    def _verificar_admin(self):
        import hashlib
        h = hashlib.sha256(self._admin_pwd.get().encode()).hexdigest()
        if h == ADMIN_HASH:
            self._admin_desbloqueado = True
            self._frm_admin_lock.pack_forget()
            self._frm_admin_panel.pack(fill="both", expand=True)
            self._admin_pwd.set("")
            self._refrescar_lista_patrones()
        else:
            self._lbl_admin_err.config(text="Password incorrecto")
            self._admin_pwd.set("")

    def _cerrar_admin(self):
        self._admin_desbloqueado = False
        self._frm_admin_panel.pack_forget()
        self._frm_admin_lock.pack(fill="both", expand=True)

    def _agregar_patron(self):
        nombre = self._pnom.get()
        if not nombre:
            messagebox.showwarning("Aviso", "El nombre es obligatorio"); return
        datos = {
            "nombre":      nombre,
            "instrumento": self._pinst.get(),
            "certificado": self._pcert.get(),
            "vigencia":    self._pvig.get() or None,
            "u_mm":        self._pU.get(),
            "k":           self._pk.get(),
            "activo":      True,
        }
        ok, resp = _supabase_insert("patrones", datos)
        if ok:
            self._lbl_admin_err.config(
                text="Patron agregado: {}".format(nombre), fg=ACC)
            self._pnom.set(""); self._pcert.set("")
            self._pvig.set(""); self._pU.set(0.0001); self._pk.set(2)
            self._refrescar_lista_patrones()
            self._cargar_patrones()
        else:
            self._lbl_admin_err.config(
                text="Error: {}".format(resp[:80]), fg="#ef4444")

    def _refrescar_lista_patrones(self):
        for w in self._pat_inner.winfo_children():
            w.destroy()
        data = _supabase_get("patrones", "order=nombre.asc")
        if not data:
            tk.Label(self._pat_inner, text="Sin patrones registrados",
                     bg=BG, fg=TEXT2, font=FONT).pack(pady=10)
            return
        for p in data:
            row = tk.Frame(self._pat_inner, bg=BG2,
                           highlightthickness=1, highlightbackground=BG3)
            row.pack(fill="x", padx=8, pady=3)
            activo_color = ACC if p.get("activo") else "#ef4444"
            activo_txt   = "ACTIVO" if p.get("activo") else "INACTIVO"
            info = "{} | Cert: {} | Vig: {} | U={} mm | k={}".format(
                p.get("nombre","---"), p.get("certificado","---"),
                p.get("vigencia","---"), p.get("u_mm","---"), p.get("k","---"))
            tk.Label(row, text=info, bg=BG2, fg=TEXT, font=FONT,
                     anchor="w").pack(side="left", padx=8, pady=4, fill="x", expand=True)
            tk.Label(row, text=activo_txt, bg=BG2, fg=activo_color,
                     font=FONTB).pack(side="left", padx=6)
            pid = p.get("id","")
            tk.Button(row, text="Desactivar" if p.get("activo") else "Activar",
                      command=lambda i=pid, a=p.get("activo"): self._toggle_patron(i, a),
                      bg=BG3, fg=TEXT2, font=FONT, relief="flat",
                      padx=6, cursor="hand2").pack(side="left", padx=4, pady=4)
            tk.Button(row, text="X Eliminar",
                      command=lambda i=pid, n=p.get("nombre",""): self._eliminar_patron(i, n),
                      bg=BG3, fg="#ef4444", font=FONT,
                      relief="flat", padx=6, cursor="hand2").pack(side="left", padx=4, pady=4)

    def _toggle_patron(self, pid, activo_actual):
        url = "{}/rest/v1/patrones?id=eq.{}".format(SUPABASE_URL, pid)
        body = json.dumps({"activo": not activo_actual}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PATCH",
            headers={"apikey": SUPABASE_KEY,
                     "Authorization": "Bearer " + SUPABASE_KEY,
                     "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self._refrescar_lista_patrones(); self._cargar_patrones()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _eliminar_patron(self, pid, nombre):
        if not messagebox.askyesno("Confirmar", "Eliminar: {}?".format(nombre)): return
        if _supabase_delete("patrones", pid):
            self._refrescar_lista_patrones(); self._cargar_patrones()
        else:
            messagebox.showerror("Error", "No se pudo eliminar")

        for w in self._meds_inner.winfo_children():
            w.destroy()
        self._campos_meds = []
        try:
            rmin = self.rango_min.get(); rmax = self.rango_max.get()
        except:
            rmin, rmax = 0, 25

        # Puntos PC-013: cada 2.5 mm para rango 0-25
        paso = 2.5
        n = int(round((rmax - rmin) / paso)) + 1
        pts = [round(rmin + i * paso, 4) for i in range(n)]
        # Si rmax no esta incluido exactamente
        if pts[-1] != rmax:
            pts.append(rmax)

        for i, nom in enumerate(pts):
            s = _sec(self._meds_inner,"PUNTO {}  |  {:.3f} mm".format(i+1, nom))
            s.pack(fill="x", padx=6, pady=2)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=4)

            corr = NumField(frm,"Correccion bloque cert. (mm):","0.0",width=10)
            corr.pack(anchor="w", pady=1)
            tb   = NumField(frm,"Temp. bloque (C):","20.0",width=8)
            tb.pack(anchor="w", pady=1)

            lecs = []
            for j in range(CONFIG["n_lecturas"]):
                c = NumField(frm,"  Lectura X{} (mm):".format(j+1),"{:.4f}".format(nom),width=10)
                c.pack(anchor="w", pady=1)
                lecs.append(c)

            ti = NumField(frm,"Temp. micrometro (C):","20.0",width=8)
            ti.pack(anchor="w", pady=1)

            self._campos_meds.append({
                "nominal":nom,"corr":corr,"T_bloque":tb,"lecturas":lecs,"T_mic":ti
            })

    # ── TAB GENERAR PDF ───────────────────────────────────────
    def _tab_generar(self, f):
        s = _sec(f,"Datos del certificado"); s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        self.fecha_cal = StrField(frm,"Fecha calibracion (aaaa-mm-dd):",
                                   datetime.date.today().strftime("%Y-%m-%d"),width=14)
        self.prox_cal  = StrField(frm,"Proxima calibracion:","A solicitud del usuario",width=28)
        self.resp_nom  = StrField(frm,"Nombre responsable tecnico:","",width=30)
        self.resp_reg  = StrField(frm,"Registro CFP:","",width=14)
        for w in [self.fecha_cal, self.prox_cal, self.resp_nom, self.resp_reg]:
            w.pack(anchor="w", pady=2)

        s2 = _sec(f,"Destino del PDF"); s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=5)
        self.pdf_dest = tk.StringVar()
        _entry(frm2, self.pdf_dest, 50).pack(side="left", padx=(0,6))
        tk.Button(frm2, text="Elegir carpeta...", command=self._elegir_carpeta,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="left")

        tk.Button(f, text="  GENERAR CERTIFICADO PDF  ",
                  command=lambda: threading.Thread(target=self._generar,daemon=True).start(),
                  bg=ACC, fg="#000", font=("Segoe UI",12,"bold"),
                  relief="flat", padx=18, pady=8, cursor="hand2").pack(pady=12)

        self.log = scrolledtext.ScrolledText(f, height=11, bg=BG2, fg=TEXT,
                                              font=("Consolas",9), relief="flat",
                                              insertbackground=ACC)
        self.log.pack(fill="both", expand=True, padx=10, pady=(0,8))

    def _elegir_carpeta(self):
        folder = filedialog.askdirectory(title="Carpeta de destino")
        if folder:
            cod = self._ev["eq_cert"].get() or "certificado"
            cod = cod.replace("/","-").replace("\\","-")
            self.pdf_dest.set(os.path.join(folder,"certificado_{}.pdf".format(cod)))

    def _log(self, msg):
        self.log.insert("end", msg+"\n")
        self.log.see("end")
        self.update_idletasks()

    def _generar(self):
        self.log.delete("1.0","end")
        self._log("Iniciando generacion del certificado...")
        try:
            tipo = self.inst_tipo.get()
            m    = 5 if tipo=="Analogica" else 2
            unidad = self.inst_unidad.get()
            res_val = self.inst_res.get()
            rmin_val = self.rango_min.get()
            rmax_val = self.rango_max.get()
            # Convertir a mm para calculos internos
            if unidad == "pulg":
                res_mm   = res_val * MM_POR_PULGADA
                rmin_mm  = rmin_val * MM_POR_PULGADA
                rmax_mm  = rmax_val * MM_POR_PULGADA
            else:
                res_mm   = res_val
                rmin_mm  = rmin_val
                rmax_mm  = rmax_val
            inst = {
                "resolucion": res_mm,
                "resolucion_orig": res_val,
                "tipo":       tipo,
                "m":          m,
                "rango_min":  rmin_mm,
                "rango_max":  rmax_mm,
                "rango_min_orig": rmin_val,
                "rango_max_orig": rmax_val,
                "unidad":     unidad,
            }
            # Obtener nombre e instrumento del patron seleccionado
            idx_pat = self._combo_patron.current()
            pat_nombre = ""
            pat_instrumento = "Bloques patron de longitud (gauge blocks)"
            if idx_pat >= 0 and idx_pat < len(self._patrones_lista):
                p_sel = self._patrones_lista[idx_pat]
                pat_nombre = p_sel.get("nombre","")
                pat_instrumento = p_sel.get("instrumento","Bloques patron de longitud (gauge blocks)")

            patron = {
                "certificado":  self.pat_cert.get(),
                "vigencia":     self.pat_vig.get(),
                "U":            self.pat_U.get(),
                "k":            self.pat_k.get(),
                "nombre":       pat_nombre,
                "instrumento":  pat_instrumento,
            }
            c_ini = {
                "temperatura": self.cond_inicio_t.get(),
                "humedad":     self.cond_inicio_h.get(),
                "presion":     self.cond_inicio_p.get(),
            }
            c_fin = {
                "temperatura": self.cond_fin_t.get(),
                "humedad":     self.cond_fin_h.get(),
                "presion":     self.cond_fin_p.get(),
            }
            planitud = {
                "tope_fijo_bandas":    int(self.plan_fijo_b.get()),
                "tope_fijo_desv_um":   self.plan_fijo_d.get(),
                "tope_movil_bandas":   int(self.plan_movil_b.get()),
                "tope_movil_desv_um":  self.plan_movil_d.get(),
            }
            paralelismo = []
            for p in self._campos_paral:
                if p["frm"].winfo_exists():
                    paralelismo.append({
                        "valor_paralela_mm": p["vp"].get(),
                        "bandas":            int(p["ban"].get()),
                        "desv_um":           p["dsv"].get(),
                    })

            if not self._campos_meds:
                messagebox.showwarning("Aviso","Genera primero los puntos en la pestana Mediciones")
                return

            mediciones = []
            for dp in self._campos_meds:
                nom  = dp["nominal"]  # ya en mm
                corr_orig = dp["corr"].get()
                lecs_orig = [c.get() for c in dp["lecturas"]]
                # Si unidad es pulgadas, convertir corrección y lecturas a mm
                if unidad == "pulg":
                    corr = pulg_a_mm(corr_orig)
                    lecs = [pulg_a_mm(l) for l in lecs_orig]
                else:
                    corr = corr_orig
                    lecs = lecs_orig
                LBP = nom + corr
                mediciones.append({
                    "nominal":  nom,
                    "corr_cert":corr,
                    "LBP":      LBP,
                    "T_bloque": dp["T_bloque"].get(),
                    "T_mic":    dp["T_mic"].get(),
                    "lecturas": lecs,
                })

            self._log("  Calculando GUM PC-013...")
            res, comps = calcular_todo(
                mediciones, inst, patron, planitud, paralelismo,
                c_ini, c_fin, caras=self.inst_caras.get()
            )

            cod = self._ev["eq_cert"].get().strip()
            if not cod:
                messagebox.showwarning("Aviso", "Debe ingresar el codigo de certificado en la pestana JSON/Equipo")
                return
            cfg_eq = {
                "codigo_certificado": cod,
                "descripcion":  "Micrometro de Exteriores",
                "marca":        self._ev["eq_marca"].get(),
                "modelo":       self._ev["eq_modelo"].get(),
                "serie":        self._ev["eq_serie"].get(),
                "codigo_interno": self._ev["eq_codigo"].get(),
                "ot":           self._ev["eq_ot"].get(),
                "guia":         self._ev["eq_guia"].get(),
                "datos_adicionales": "",
                "cliente": {
                    "nombre":    self._ev["eq_cliente"].get(),
                    "ruc":       self._ev["eq_ruc"].get(),
                    "direccion": self._ev["eq_dir"].get(),
                },
            }

            pdf_dest = self.pdf_dest.get().strip()
            if not pdf_dest:
                carpeta = os.path.dirname(self.json_path.get()) or os.getcwd()
                pdf_dest = os.path.join(carpeta,"certificado_{}.pdf".format(cod.replace("/","_")))
                self.pdf_dest.set(pdf_dest)

            carpeta_pdf = os.path.dirname(os.path.abspath(pdf_dest))
            ruta_img    = os.path.join(carpeta_pdf,"_grafico_mic_tmp.png")

            self._log("  Generando grafico...")
            _grafico(res, ruta_img)

            self._log("  Construyendo PDF...")
            generar_pdf(
                cfg_eq, inst, patron, planitud, paralelismo,
                c_ini, c_fin, res, comps,
                pdf_dest, ruta_img,
                fecha_cal=self.fecha_cal.get(),
                total_pags=3,
                responsable_nombre=self.resp_nom.get(),
                responsable_reg=self.resp_reg.get(),
                proxima_calibracion=self.prox_cal.get(),
            )

            if os.path.exists(ruta_img):
                os.remove(ruta_img)

            self._log("\nPDF generado: " + pdf_dest)
            self._log("\n-- Resumen --")
            for r in res:
                self._log("  L={:.3f} mm | Error={:.2f} um | U={:.1f} um | EMP={} um | {}".format(
                    r["nominal"], r["error_um"], r["U_um"],
                    r["EMP_um"], "OK" if r["cumple"] else "FUERA"))
            self._log("  f_max = {:.1f} um".format(comps["f_max"]))
            self._log("  U_max = +/- {:.1f} um".format(comps["U_max"]))

            # ── REGISTRO LOCAL + SUPABASE ──────────────────────
            registro = {
                "codigo":            cod,
                "ot_number":         self._ev["eq_ot"].get(),
                "magnitud":          "longitud",
                "equipo":            "Micrometro de Exteriores",
                "marca":             self._ev["eq_marca"].get(),
                "modelo":            self._ev["eq_modelo"].get(),
                "numero_serie":      self._ev["eq_serie"].get(),
                "cliente":           self._ev["eq_cliente"].get(),
                "ruc":               self._ev["eq_ruc"].get(),
                "direccion":         self._ev["eq_dir"].get(),
                "estado":            "emitido",
                "fecha_calibracion": self.fecha_cal.get(),
                "fecha_emision":     datetime.date.today().isoformat(),
                "proxima_cal":       self.prox_cal.get(),
                "tecnico_nombre":    self.resp_nom.get(),
                "resolucion_mm":     inst["resolucion"],
                "tipo_instrumento":  inst["tipo"],
                "rango_min_mm":      inst["rango_min"],
                "rango_max_mm":      inst["rango_max"],
                "temp_ini":          c_ini["temperatura"],
                "temp_fin":          c_fin["temperatura"],
                "hr_ini":            c_ini["humedad"],
                "hr_fin":            c_fin["humedad"],
                "patron_cert":       patron["certificado"],
                "patron_vigencia":   patron["vigencia"],
                "patron_U_mm":       patron["U"],
                "patron_k":          patron["k"],
                "err_E_um":          planitud["tope_fijo_desv_um"],
                "err_R_um":          comps["u_A_max"],
                "err_SEI_um":        planitud["tope_movil_desv_um"],
                "err_SEP_um":        comps["u_paral"],
                "err_L_um":          comps["u_plan"],
                "err_J_um":          comps["u_div"],
                "err_K_um":          comps["u_term_max"],
                "resultados_json": [
                    {
                        "nominal_mm": r["nominal"],
                        "LBP_mm":     r["LBP"],
                        "media_mm":   r["media"],
                        "error_um":   round(r["error_um"],4),
                        "U_um":       round(r["U_um"],4),
                        "EMP_um":     r["EMP_um"],
                        "cumple":     r["cumple"],
                        "lecturas":   r["lecturas"],
                    }
                    for r in res
                ],
                "ruta_pdf":    pdf_dest,
                "observaciones": "f_max={:.1f} um | U_max=+/-{:.1f} um".format(
                    comps["f_max"], comps["U_max"]),
            }

            ruta_reg = os.path.join(carpeta_pdf,
                "registro_{}.json".format(cod.replace("/","_").replace("\\","_")))
            self._log("\nGuardando registro local...")
            guardar_registro_json(ruta_reg, registro)
            self._log("  " + ruta_reg)

            self._log("Subiendo a Supabase...")
            ok, resp = _supabase_upsert("certificados", registro)
            if ok:
                self._log("  OK - guardado en Supabase")
                self._marcar_pendiente_completado(cod)
            else:
                self._log("  AVISO: " + resp[:120])

            # Abrir PDF automaticamente
            try:
                import subprocess
                subprocess.Popen(['start', '', pdf_dest], shell=True)
            except:
                pass

            messagebox.showinfo("Exito",
                "PDF generado:\n{}\n\nRegistro guardado:\n{}".format(pdf_dest, ruta_reg))

        except Exception as e:
            self._log("\nERROR: " + str(e))
            self._log(traceback.format_exc())
            messagebox.showerror("Error", str(e))


# ============================================================
# LOGIN
# ============================================================
PASSWORD_HASH = "65340a57c9343c3417b4ed42ea446102cbff73ebd161636fc8bfd2a9b41167b9"
ADMIN_HASH    = "cc4e4e0a01063aa9bcdf44393e77647d12a81743d5a5d2813c7111096c9682f5"

class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Acceso")
        self.configure(bg="#1a1a2e")
        self.resizable(False, False)
        self._autenticado = False
        self._build()
        self.update_idletasks()
        w,h = 340,220
        x = (self.winfo_screenwidth()-w)//2
        y = (self.winfo_screenheight()-h)//2
        self.geometry("{}x{}+{}+{}".format(w,h,x,y))

    def _build(self):
        tk.Label(self, text="METROMECANICA", bg="#1a1a2e", fg="#00d4aa",
                 font=("Segoe UI",13,"bold")).pack(pady=(24,2))
        tk.Label(self, text="Calibracion Micrometro de Exteriores",
                 bg="#1a1a2e", fg="#aaaaaa", font=("Segoe UI",9)).pack(pady=(0,18))
        frm = tk.Frame(self, bg="#1a1a2e"); frm.pack()
        tk.Label(frm, text="Contrasena:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Segoe UI",9)).grid(row=0, column=0, sticky="e", padx=(0,6))
        self._pwd = tk.StringVar()
        e = tk.Entry(frm, textvariable=self._pwd, show="*", width=18,
                     bg="#16213e", fg="#e0e0e0", insertbackground="#00d4aa",
                     relief="flat", font=("Segoe UI",10),
                     highlightthickness=1, highlightbackground="#0f3460",
                     highlightcolor="#00d4aa")
        e.grid(row=0, column=1); e.focus()
        e.bind("<Return>", lambda ev: self._verificar())
        self._lbl_err = tk.Label(self, text="", bg="#1a1a2e", fg="#e94560",
                                  font=("Segoe UI",8))
        self._lbl_err.pack(pady=6)
        tk.Button(self, text="Ingresar", command=self._verificar,
                  bg="#00d4aa", fg="#000", font=("Segoe UI",10,"bold"),
                  relief="flat", padx=20, pady=5, cursor="hand2").pack()

    def _verificar(self):
        ingresado = hashlib.sha256(self._pwd.get().encode()).hexdigest()
        if ingresado == PASSWORD_HASH:
            self._autenticado = True
            self.destroy()
        else:
            self._lbl_err.config(text="Contrasena incorrecta")
            self._pwd.set("")


if __name__ == "__main__":
    login = LoginWindow()
    login.mainloop()
    if not login._autenticado:
        sys.exit(0)
    app = MicApp()
    app.mainloop()
