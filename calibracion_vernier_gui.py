"""
============================================================
CALIBRACIÓN PIE DE REY — GUI PORTABLE
Metromecanica | PC-012 INDECOPI | ISO/IEC 17025
============================================================
Instrucciones:
  1. Coloca este archivo en cualquier carpeta
  2. En esa misma carpeta pon el config_calibracion_XXX.json
  3. Ejecuta:  python calibracion_vernier_gui.py
  4. El PDF se genera en la carpeta que elijas
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

# ============================================================
# SUPABASE
# ============================================================
SUPABASE_URL = "https://ndcjjksaiecsuzperrhp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5kY2pqa3NhaWVjc3V6cGVycmhwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjU5OTE4MiwiZXhwIjoyMDg4MTc1MTgyfQ.pdgxsNk-33mBuKCI_wxhYHxvz2h8POmBvhR69Tqsw6o"

def _supabase_get(tabla, filtro=None):
    """Lee registros de Supabase."""
    url = "{}/rest/v1/{}?select=*".format(SUPABASE_URL, tabla)
    if filtro:
        url += "&" + filtro
    req = urllib.request.Request(url, method="GET",
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type":  "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return []

def _supabase_delete(tabla, id_val):
    url = "{}/rest/v1/{}?id=eq.{}".format(SUPABASE_URL, tabla, id_val)
    req = urllib.request.Request(url, method="DELETE",
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type":  "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except:
        return False

def _supabase_upsert(tabla, datos):
    """Inserta o actualiza un registro en Supabase via REST."""
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

def guardar_registro_json(ruta_json, registro):
    """Guarda el registro completo de calibracion en un JSON local."""
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

# ============================================================
# CONFIG
# ============================================================
CONFIG = {
    "razon_social"       : "METROMECANICA INGENIERIA Y METROLOGIA S.A.C.",
    "area_laboratorio"   : "Laboratorio de Longitud y Angulo",
    "lugar_calibracion"  : "Laboratorio de Longitud y Angulo - METROMECANICA",
    "metodo_texto"       : (
        "Procedimiento de calibracion por comparacion directa con bloques patron de longitud, "
        "bajo los lineamientos del PC-012 INDECOPI 5ta Ed. 2012 / ISO 13385-1:2011."
    ),
    "aprobador_nombre"   : "Responsable Tecnico",
    "aprobador_reg"      : "0000",
    "norma_procedimiento": "PC-DIM-001",
    "version_proc"       : "Rev. 02",
    "norma_base"         : "PC-012 INDECOPI 5ta Ed. 2012 / ISO 13385-1:2011",
    "temp_referencia"    : 20.0,
    "alpha_BP"           : 11.5e-6,
    "Delta_alpha_BP"     : 1.0e-6,
    "alpha_i"            : 11.5e-6,
    "Delta_alpha_i"      : 1.0e-6,
    "termometro_UT_cert" : 0.5,
    "termometro_k"       : 2.0,
    "termometro_d"       : 0.1,
    "termometro_m"       : 2,
    "termometro_UTder"   : 0.5,
    "grado_bloques"      : "1",
    "factor_cobertura"   : 2,
    "nivel_confianza"    : "95 %",
    "n_puntos"           : 5,
    "n_repeticiones"     : 5,
    "unidad"             : "mm",
}

W = A4[0]; H = A4[1]
NEGRO  = colors.black
GRIS   = colors.HexColor('#555555')
GRIS_C = colors.HexColor('#CCCCCC')
GRIS_F = colors.HexColor('#F0F0F0')

# ============================================================
# FORMATO DECIMAL CON COMA (norma metrologica peruana)
# ============================================================
def fc(valor, decimales=3):
    """Formatea un numero usando coma como separador decimal."""
    fmt = "{:.Xf}".replace("X", str(decimales))
    return fmt.format(float(valor)).replace(".", ",")

# ============================================================
# MATEMATICAS
# ============================================================
def _media(v):  return sum(v)/len(v)
def _s(v):
    m=_media(v); return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1)) if len(v)>1 else 0.
def _rect(a):   return a/math.sqrt(3)
def _norm(U,k): return U/k
def _uc(cs):    return math.sqrt(sum(c**2 for c in cs))

def _error_indicacion(Li, Li_T, LBP, LBP_T, alpha_i, alpha_BP, T_ref=20.0):
    return Li*(1+alpha_i*(Li_T-T_ref)) - LBP*(1+alpha_BP*(LBP_T-T_ref))

def _deriva_bloque(L_mm, grado):
    if grado in ("K","0"): return 0.02e-3 + 0.25e-6*L_mm
    return 0.05e-3 + 0.5e-6*L_mm

def _u_termometro(UT_cert, k_t, Delta_t, d_T, m_T, UT_der):
    return math.sqrt((UT_cert/k_t)**2+(Delta_t/math.sqrt(3))**2+
                     (d_T/m_T/math.sqrt(3))**2+(UT_der/math.sqrt(3))**2)

def puntos_nominales(rmin, rmax, n):
    return [round(rmin+i*(rmax-rmin)/(n-1),4) for i in range(n)]

def calcular_todo(mediciones, inst, patron, errores_dim, c_ini, c_fin):
    cfg=CONFIG; T_ref=cfg["temp_referencia"]
    alpha_i=cfg["alpha_i"]; alpha_BP=cfg["alpha_BP"]; k2=cfg["factor_cobertura"]

    T_vals=([c_ini["temperatura"],c_fin["temperatura"]]+
            [d["T_bloque"] for d in mediciones]+[d["T_inst"] for d in mediciones])
    dT_max=max(abs(t-T_ref) for t in T_vals)
    u_dT=_u_termometro(cfg["termometro_UT_cert"],cfg["termometro_k"],
                        dT_max,cfg["termometro_d"],cfg["termometro_m"],cfg["termometro_UTder"])
    u_dalpha=math.sqrt(_rect(cfg["Delta_alpha_BP"])**2+_rect(cfg["Delta_alpha_i"])**2)
    u_alpha_BP=_rect(cfg["Delta_alpha_BP"])

    E=errores_dim["E"]; Rum=errores_dim["R_um"]
    SEI=errores_dim["SEI"]; SEP=errores_dim["SEP"]
    L=errores_dim["L"]; J=errores_dim["J"]; K=errores_dim["K"]
    d=inst["resolucion"]*1000; m=inst["m"]

    u_E  =E/(2*math.sqrt(3)); u_R=Rum/math.sqrt(len(errores_dim["R_lecs"]))
    u_S  =max(SEI,SEP)/(2*math.sqrt(3)); u_L=L/(2*math.sqrt(3))
    u_J  =J/(2*math.sqrt(3)); u_K=K/(2*math.sqrt(3)); u_res=(d/m)/math.sqrt(3)
    u_Li_um=math.sqrt(u_E**2+u_R**2+u_S**2+u_L**2+u_J**2+u_K**2+u_res**2)

    u_BP_cal=_norm(patron["U"],patron["k"])
    resultados=[]
    for dp in mediciones:
        nom=dp["nominal"]; LBP=dp["LBP"]; lecs=dp["lecturas"]
        T_B=dp["T_bloque"]; T_I=dp["T_inst"]; med=_media(lecs)
        error=_error_indicacion(med,T_I,LBP,T_B,alpha_i,alpha_BP,T_ref)
        u_BP_der=_deriva_bloque(LBP,cfg["grado_bloques"])
        u_BP=math.sqrt(u_BP_cal**2+u_BP_der**2)
        dTi=T_I-T_ref; dT_pt=abs(dTi-(T_B-T_ref))
        u_Li_mm=u_Li_um/1000.
        uc=_uc([u_Li_mm,u_BP,LBP*alpha_BP*u_dT,LBP*dT_pt*u_alpha_BP,
                LBP*dTi*u_dalpha,LBP*(alpha_i-alpha_BP)*u_dT])
        U_exp=k2*uc
        resultados.append({"nominal":nom,"LBP":LBP,"T_bloque":T_B,"T_inst":T_I,
                            "lecturas":lecs,"media":med,"desv":_s(lecs),
                            "error_um":error*1000,"corr_um":-error*1000,
                            "error_mm":error,"corr_mm":-error,
                            "u_Li_um":u_Li_um,"u_BP_mm":u_BP,
                            "u_c_mm":uc,"U_exp_mm":U_exp,"U_exp_um":U_exp*1000})

    tramos=[]
    prev=0.
    for r in sorted(resultados,key=lambda x:x["nominal"]):
        tramos.append({"de":prev,"hasta":r["nominal"],
                       "U_um":r["U_exp_um"],"U_um_red":round(r["U_exp_um"])})
        prev=r["nominal"]

    U0=resultados[0]["U_exp_um"] if resultados else u_Li_um*k2
    Um=max(r["U_exp_um"] for r in resultados)
    Lm=max(r["nominal"]  for r in resultados)
    B_sq=max(0,(Um**2-U0**2)/(Lm**2)) if Lm>0 else 0
    comps={"u_Li_um":u_Li_um,"u_BP_cal_mm":u_BP_cal,
           "A_coef":math.sqrt(U0**2),"B_coef":math.sqrt(B_sq)}
    return resultados,tramos,comps

def _grafico(resultados, ruta):
    x=[r["LBP"] for r in resultados]
    y=[r["error_um"] for r in resultados]
    fig,ax=plt.subplots(figsize=(6.5,3.4),dpi=160)
    fig.patch.set_facecolor('white'); ax.set_facecolor('white')
    ax.plot(x,y,color='black',linewidth=1.2,marker='D',markersize=4.5,
            markerfacecolor='black',markeredgecolor='black')
    ax.axhline(0,color='black',linewidth=0.6)
    ax.set_xlabel('Valor Nominal  ( mm )',fontsize=8)
    ax.set_ylabel('Error de la medicion\n( µm )',fontsize=8)
    ax.set_title('Error De Indicacion del Pie de Rey',fontsize=9,fontweight='bold')
    ax.tick_params(labelsize=7.5)
    ax.grid(True,linestyle='-',linewidth=0.3,color='#AAAAAA',alpha=0.7)
    ax.set_xlim(left=0)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    for sp in ax.spines.values():
        sp.set_edgecolor('black'); sp.set_linewidth(0.6)
    plt.tight_layout(pad=0.8)
    plt.savefig(ruta,dpi=160,bbox_inches='tight',facecolor='white')
    plt.close()

def _es():
    return {
        "tit_cert": ParagraphStyle('tc', fontName='Helvetica', fontSize=14, leading=18, alignment=TA_CENTER, spaceAfter=2),
        "tit_pag" : ParagraphStyle('tp', fontName='Helvetica', fontSize=10, leading=13, alignment=TA_CENTER),
        "sub_pag" : ParagraphStyle('sp', fontName='Helvetica', fontSize=8, leading=11, alignment=TA_CENTER, textColor=GRIS),
        "pag_r"   : ParagraphStyle('pr', fontName='Helvetica', fontSize=8, leading=10, alignment=TA_RIGHT, textColor=GRIS),
        "sec_num" : ParagraphStyle('sn', fontName='Helvetica-Bold', fontSize=8, leading=11, spaceBefore=2),
        "lbl"     : ParagraphStyle('lb', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_LEFT, textColor=GRIS),
        "val"     : ParagraphStyle('vl', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_LEFT),
        "nor"     : ParagraphStyle('no', fontName='Helvetica', fontSize=7.5, leading=11, alignment=TA_LEFT),
        "nor_b"   : ParagraphStyle('nb', fontName='Helvetica-Bold', fontSize=8, leading=11, alignment=TA_LEFT),
        "nor_r"   : ParagraphStyle('nr', fontName='Helvetica', fontSize=8, leading=11, alignment=TA_RIGHT),
        "cen"     : ParagraphStyle('cn', fontName='Helvetica', fontSize=7.5, leading=10, alignment=TA_CENTER),
        "decl"    : ParagraphStyle('dc', fontName='Helvetica', fontSize=6.5, leading=9, alignment=TA_JUSTIFY, textColor=GRIS),
        "nota_pie": ParagraphStyle('np', fontName='Helvetica', fontSize=7, leading=9.5, alignment=TA_LEFT, textColor=GRIS),
        "unc"     : ParagraphStyle('uc', fontName='Helvetica-Bold', fontSize=8, leading=12, alignment=TA_LEFT),
        "fin_doc" : ParagraphStyle('fd', fontName='Helvetica', fontSize=8, leading=11, alignment=TA_CENTER, textColor=GRIS),
        "sec"     : ParagraphStyle('sc', fontName='Helvetica-Bold', fontSize=8, leading=11, spaceBefore=2),
    }

def _ts(hdr=GRIS_F):
    return TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7.5),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),('GRID',(0,0),(-1,-1),0.4,NEGRO),
        ('BACKGROUND',(0,0),(-1,0),hdr),('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2.5),
        ('BOTTOMPADDING',(0,0),(-1,-1),2.5),('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
    ])

def _ts_mini(hdr=GRIS_F):
    return TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),
        ('FONTNAME',(0,1),(-1,-1),'Helvetica'),('GRID',(0,0),(-1,-1),0.4,NEGRO),
        ('BACKGROUND',(0,0),(-1,0),hdr),('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2),
        ('BOTTOMPADDING',(0,0),(-1,-1),2),('LEFTPADDING',(0,0),(-1,-1),3),
        ('RIGHTPADDING',(0,0),(-1,-1),3),
    ])

def generar_pdf(cfg_eq, inst, patron, errores_dim, c_ini, c_fin,
                resultados, tramos, comps, err_inicial,
                ruta_pdf, ruta_img, fecha_cal, total_pags=3,
                responsable_nombre="", responsable_reg="",
                proxima_calibracion="A solicitud del usuario",
                emp_maximo_permisible=None):

    es=_es(); ahora=datetime.datetime.now()
    cod=cfg_eq.get("codigo_certificado","---"); pag=[0]

    def on_page(canvas, doc):
        pag[0]+=1
        canvas.saveState()
        canvas.setFont("Helvetica",7); canvas.setFillColor(GRIS)
        canvas.drawCentredString(W/2, 10*mm,
            "Certificado de Calibracion  {}  |  Pag. {} de {}".format(cod, pag[0], total_pags))
        canvas.restoreState()

    doc=SimpleDocTemplate(ruta_pdf, pagesize=A4,
        rightMargin=50*mm, leftMargin=50*mm,
        topMargin=50*mm,   bottomMargin=50*mm,
        title="Certificado de Calibracion {}".format(cod))

    s=[]; sep=lambda n=2: s.append(Spacer(1,n*mm))
    hr =lambda: s.append(HRFlowable(width="100%",thickness=0.5,color=GRIS_C))
    hr1=lambda: s.append(HRFlowable(width="100%",thickness=0.3,color=GRIS_C))

    cli=cfg_eq.get("cliente",{})

    s.append(Paragraph("Certificado de Calibracion<br/><b>{}</b>".format(cod), es["tit_cert"]))
    sep(1)

    t=Table([
        [Paragraph("<b>Orden de Trabajo :</b>  {}  -  {}".format(cfg_eq.get('ot','---'), CONFIG['area_laboratorio']),es["nor"]),
         Paragraph("<b>Fecha de Emision :</b>  {}".format(ahora.strftime('%Y-%m-%d')),es["nor_r"])],
        [Paragraph("<b>N Guia :</b>  {}".format(cfg_eq.get('guia','---')),es["nor"]),
         Paragraph("<b>Pagina 1 de {}</b>".format(total_pags),es["nor_r"])],
    ],colWidths=[100*mm,60*mm])
    t.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    s.append(t); sep(2); hr(); sep(2)

    def sec(num,titulo):
        return Paragraph("<b>{}.-  {}</b>".format(num,titulo), es["sec_num"])

    def lbl_val(label, valor):
        return Table([[Paragraph(label,es["lbl"]),Paragraph(":  {}".format(valor),es["val"])]],
            colWidths=[38*mm,72*mm],
            style=TableStyle([("TOPPADDING",(0,0),(-1,-1),1),
                              ("BOTTOMPADDING",(0,0),(-1,-1),1),
                              ("VALIGN",(0,0),(-1,-1),"TOP")]))

    rango_str=fc(resultados[0]['nominal'],1)+' mm a '+fc(resultados[-1]['nominal'],1)+' mm'
    col_izq=[]

    col_izq.append(sec("1","Informacion del solicitante")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(lbl_val("Nombre o Razon Social", "<b>{}</b>".format(cli.get('nombre','---'))))
    col_izq.append(lbl_val("Direccion", cli.get("direccion","---")))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("2","Informacion del Equipo")); col_izq.append(Spacer(1,1*mm))
    for label,valor in [
        ("Descripcion",    cfg_eq.get("descripcion","---")),
        ("Marca",          cfg_eq.get("marca","---")),
        ("Modelo",         cfg_eq.get("modelo","---")),
        ("Serie",          cfg_eq.get("serie","---")),
        ("Identificacion", "{}  (*)".format(cfg_eq.get('codigo_interno','---'))),
        ("Rango de Medicion", rango_str),
        ("Resolucion",     "{} mm".format(inst['resolucion'])),
        ("Tipo",           inst["tipo"]),
    ]:
        col_izq.append(lbl_val(label, valor))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("3","Fecha de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}  (**)".format(fecha_cal),es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("4","Lugar de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}".format(CONFIG['lugar_calibracion']),es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("5","Metodo de Calibracion")); col_izq.append(Spacer(1,1*mm))
    col_izq.append(Paragraph("    {}".format(CONFIG['metodo_texto']),es["nor"]))
    col_izq.append(Spacer(1,3*mm))

    col_izq.append(sec("6","Condiciones Ambientales")); col_izq.append(Spacer(1,1*mm))
    t_cond=Table([
        [Paragraph("<b>Temperatura</b>",es["cen"]),Paragraph("<b>Humedad</b>",es["cen"])],
        [Paragraph(fc(c_ini['temperatura'],1)+' C  a  '+fc(c_fin['temperatura'],1)+' C',es["cen"]),
         Paragraph(fc(c_ini['humedad'],1)+' %HR  a  '+fc(c_fin['humedad'],1)+' %HR',es["cen"])],
    ],colWidths=[55*mm,55*mm])
    t_cond.setStyle(TableStyle([
        ("FONTSIZE",(0,0),(-1,-1),7.5),("GRID",(0,0),(-1,-1),0.4,NEGRO),
        ("BACKGROUND",(0,0),(-1,0),GRIS_F),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    col_izq.append(t_cond)
    col_izq.append(Spacer(1,15*mm))

    decls=[
        "Los resultados del certificado son validos solo para el equipo calibrado.",
        "Este certificado es trazable a patrones nacionales e internacionales (SI).",
        "No podra ser reproducido parcialmente sin autorizacion escrita previa de {}.".format(CONFIG['razon_social']),
        "No es valido sin la firma del responsable tecnico.",
        "Se recomienda calibrar los equipos a intervalos apropiados.",
    ]
    col_der=[]
    for txt in decls:
        col_der.append(Paragraph(txt,es["decl"]))
        col_der.append(Spacer(1,3*mm))

    t_dos=Table([[col_izq,col_der]],colWidths=[115*mm,45*mm])
    t_dos.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    s.append(t_dos)

    # PAGINA 2
    s.append(PageBreak())
    s.append(Paragraph("Certificado de Calibracion  <b>{}</b>".format(cod),es["tit_pag"]))
    sep(1)
    s.append(Paragraph(CONFIG["area_laboratorio"],es["sub_pag"]))
    s.append(Paragraph("Pagina 2 de {}".format(total_pags),es["pag_r"]))
    sep(2); hr1(); sep(2)

    s.append(sec("7","Trazabilidad")); sep(1)
    pat_rows=cfg_eq.get("patrones",[{
        "vigencia":   patron.get("vigencia","---"),
        "instrumento":patron.get("instrumento","Bloques patron de longitud (gauge blocks)"),
        "certificado":patron.get("certificado","---")}])
    t_traz=Table(
        [[Paragraph("<b>Vigencia</b>",es["cen"]),
          Paragraph("<b>Equipo o Instrumento Patron</b>",es["cen"]),
          Paragraph("<b>Certificado de Calibracion</b>",es["cen"])]]+
        [[Paragraph(str(p.get("vigencia","---")),es["cen"]),
          Paragraph(str(p.get("instrumento","---")),es["cen"]),
          Paragraph(str(p.get("certificado","---")),es["cen"])]
         for p in pat_rows],
        colWidths=[30*mm,80*mm,50*mm])
    t_traz.setStyle(_ts())
    s.append(KeepTogether(t_traz)); sep(4)

    s.append(sec("8","Resultados de Calibracion")); sep(1)
    I_prom=_media(err_inicial); I_um=round(I_prom*1000,2)
    s.append(Paragraph("Error de Referencia Inicial (I) = "+fc(I_um,0)+"µm",es["nor_b"])); sep(2)

    enc_res=[
        Paragraph("<b>Indicacion\n(mm)</b>",es["cen"]),
        Paragraph("<b>Valor Conv.\nVerdadero\n(mm)</b>",es["cen"]),
        Paragraph("<b>Error\n(mm)</b>",es["cen"]),
        Paragraph("<b>Incertidumbre\n(mm)</b>",es["cen"]),
    ]

    filas_res=[enc_res]
    for r in resultados:
        fila=[
            Paragraph(fc(r['media'],3),es["cen"]),
            Paragraph(fc(r['LBP'],3),es['cen']),
            Paragraph(fc(r['error_mm'],6),es["cen"]),
            Paragraph(fc(r['U_exp_mm'],6),es["cen"]),
        ]
        filas_res.append(fila)

    t_res=Table(filas_res,colWidths=[38*mm,48*mm,35*mm,44*mm])
    t_res.setStyle(_ts())
    s.append(KeepTogether(t_res)); sep(1)
    s.append(Paragraph(
        "* k={}, {}".format(CONFIG['factor_cobertura'], CONFIG['nivel_confianza']),
        es["nota_pie"])); sep(3)

    def mini_tabla(t1,t2,vp,val):
        datos=[["VALOR\nPATRON\n( mm )","{}  {}\n( µm )".format(t1,t2)],
               [fc(vp,3),fc(val,3)]]
        t=Table(datos,colWidths=[27*mm,47*mm]); t.setStyle(_ts_mini()); return t

    def par(a,b):
        f=Table([[a,Spacer(6*mm,1),b]],colWidths=[74*mm,6*mm,74*mm])
        f.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")])); return f

    s.append(KeepTogether(par(
        mini_tabla("ERROR CONTACTO","SUP. PARCIAL  ( E )",errores_dim["bp_E"],errores_dim["E"]),
        mini_tabla("ERROR DE","REPETIBILIDAD  ( R )",errores_dim["bp_R"],errores_dim["R_um"])
    ))); sep(2)
    s.append(KeepTogether(par(
        mini_tabla("CAMBIO ESCALA","EXT - INT  ( S_EI )",errores_dim["bp_SEI"],errores_dim["SEI"]),
        mini_tabla("CAMBIO ESCALA","EXT - PROF  ( S_EP )",errores_dim["bp_SEP"],errores_dim["SEP"])
    ))); sep(2)
    s.append(KeepTogether(par(
        mini_tabla("CONTACTO","LINEAL  ( L )",errores_dim["bp_L"],errores_dim["L"]),
        mini_tabla("CONTACTO SUP.","COMPLETA  ( J )",errores_dim["bp_J"],errores_dim["J"])
    ))); sep(2)
    s.append(KeepTogether(mini_tabla("CRUCE SUP.","INTERIORES  ( K )",errores_dim["bp_K"],errores_dim["K"]))); sep(3)

    A=comps["A_coef"]; B=comps["B_coef"]
    L_max=max(r["nominal"] for r in resultados)
    s.append(Paragraph(
        "INCERTIDUMBRE: [ ( "+fc(A,2)+"^2 + "+fc(B,4)+"^2 * L^2 ) ]^(1/2)  um",
        es["nor_b"])); sep(1)
    s.append(Paragraph("L : INDICACION DEL PIE DE REY EN MILIMETROS",es["nor"])); sep(1)
    s.append(Paragraph(
        "PARA L = "+fc(L_max,0)+" mm;  U = "+fc(resultados[-1]['U_exp_um'],0)+"µm",
        es["nor"])); sep(3)

    s.append(KeepTogether(Image(ruta_img,width=130*mm,height=65*mm))); sep(2)
    hr1(); sep(1)
    s.append(Paragraph("Nota 1: Error interiores = Error exteriores + S_EI",es["nota_pie"])); sep(1)
    s.append(Paragraph("Nota 2: Error profundidad = Error exteriores + S_EP",es["nota_pie"]))

    # PAGINA 3
    s.append(PageBreak())
    s.append(Paragraph("Certificado de Calibracion  <b>{}</b>".format(cod),es["tit_pag"]))
    sep(1)
    s.append(Paragraph(CONFIG["area_laboratorio"],es["sub_pag"]))
    s.append(Paragraph("Pagina 3 de {}".format(total_pags),es["pag_r"]))
    sep(2); hr1(); sep(2)

    # Incertidumbre expandida — solo valor final
    s.append(sec("8","Incertidumbre de Medicion")); sep(1)
    U_max = max(r["U_exp_um"] for r in resultados)
    t_unc = Table([
        [Paragraph("<b>Incertidumbre Expandida  U  (k = {})</b>".format(CONFIG["factor_cobertura"]), es["nor_b"]),
         Paragraph("<b>+/- {} µm</b>".format(fc(U_max,2)), es["cen"])],
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
        "La incertidumbre expandida se obtuvo con k={}, probabilidad de cobertura 95%.".format(CONFIG['factor_cobertura']),
        es["nor"])); sep(3)

    s.append(sec("9","Observaciones y Recomendaciones")); sep(1)

    obs_lista=[
        "(*) Identificacion hallada en la superficie del equipo.",
        "(**) Fecha en que se realizo la calibracion.",
        "Se coloco etiqueta 'CALIBRADO' con codigo {}.".format(cod),
        "Proxima calibracion:  {}".format(proxima_calibracion),
    ]
    obs_extra=cfg_eq.get("datos_adicionales","").strip()
    if obs_extra:
        obs_lista.insert(2, obs_extra)

    for obs in obs_lista:
        s.append(Paragraph("*  {}".format(obs),es["nor"])); sep(1)

    sep(4); hr(); sep(2)
    s.append(Paragraph("Fin del Documento",es["fin_doc"]))

    doc.build(s, onFirstPage=on_page, onLaterPages=on_page)


# ============================================================
# GUI TKINTER
# ============================================================

BG    = "#1a1a2e"
BG2   = "#16213e"
BG3   = "#0f3460"
ACC   = "#00d4aa"
TEXT  = "#e0e0e0"
TEXT2 = "#aaaaaa"
FONT  = ("Segoe UI", 9)
FONTB = ("Segoe UI", 9, "bold")


def _entry(parent, var, width=12):
    return tk.Entry(parent, textvariable=var, width=width,
                    bg=BG2, fg=TEXT, insertbackground=ACC,
                    relief="flat", font=FONT,
                    highlightthickness=1, highlightbackground=BG3,
                    highlightcolor=ACC)


def _lbl(parent, text, color=None):
    return tk.Label(parent, text=text, bg=BG, fg=color or TEXT2, font=FONT, anchor="w")


def _seccion(parent, titulo):
    f = tk.Frame(parent, bg=BG)
    tk.Label(f, text="  " + titulo, bg=BG3, fg=ACC, font=FONTB,
             anchor="w", padx=6, pady=3).pack(fill="x", pady=(8, 3))
    return f


class NumField(tk.Frame):
    def __init__(self, parent, label, default="0", width=10, **kw):
        super().__init__(parent, bg=BG, **kw)
        tk.Label(self, text=label, bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0, 4))
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
        v = self.var.get().replace(",", ".")
        return float(v) if v.strip() else 0.0

    def set(self, v): self.var.set(str(v).replace(".", ","))


class StrField(tk.Frame):
    def __init__(self, parent, label, default="", width=22, **kw):
        super().__init__(parent, bg=BG, **kw)
        tk.Label(self, text=label, bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0, 4))
        self.var = tk.StringVar(value=default)
        _entry(self, self.var, width).pack(side="left", fill="x", expand=True)

    def get(self): return self.var.get().strip()
    def set(self, v): self.var.set(str(v))


class CalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calibracion Pie de Rey - Metromecanica")
        self.configure(bg=BG)
        self.geometry("920x700")
        self.cfg_eq = {}
        self._campos_meds = []
        self._build_ui()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG3, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="CALIBRACION PIE DE REY / VERNIER",
                 bg=BG3, fg=ACC, font=("Segoe UI", 13, "bold")).pack(side="left", padx=14)
        tk.Label(hdr, text="PC-012 INDECOPI | ISO/IEC 17025 | Metromecanica",
                 bg=BG3, fg=TEXT2, font=FONT).pack(side="left")

        style = ttk.Style(); style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=TEXT2, padding=[12, 5], font=FONT)
        style.map("TNotebook.Tab", background=[("selected", BG3)], foreground=[("selected", ACC)])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        tabs = [
            ("📂 JSON / Equipo",    self._tab_json),
            ("🔧 Instrumento",      self._tab_instrumento),
            ("🌡 Condiciones",      self._tab_condiciones),
            ("📏 Mediciones",       self._tab_mediciones),
            ("📐 Errores PC-012",   self._tab_errores),
            ("✅ Generar PDF",      self._tab_generar),
            ("⚙ Patrones",         self._tab_patrones),
        ]
        for titulo, build in tabs:
            frame = tk.Frame(nb, bg=BG)
            build(frame)
            nb.add(frame, text=titulo)

    # ── TAB JSON ─────────────────────────────────────────────
    def _tab_json(self, f):
        # ── Busqueda por OT desde Supabase ──
        hdr = tk.Frame(f, bg=BG3, pady=6); hdr.pack(fill="x", padx=10, pady=(8,0))
        tk.Label(hdr, text="  Buscar equipo pendiente por N° OT (Supabase)",
                 bg=BG3, fg=ACC, font=FONTB).pack(side="left")

        row_ot = tk.Frame(f, bg=BG); row_ot.pack(fill="x", padx=14, pady=6)
        self._ot_buscar = tk.StringVar()
        _entry(row_ot, self._ot_buscar, 20).pack(side="left", padx=(0,6))
        tk.Button(row_ot, text="🔍 Buscar en Supabase", command=self._buscar_por_ot,
                  bg=ACC, fg="#000", font=FONTB, relief="flat", padx=10, pady=4, cursor="hand2"
                  ).pack(side="left", padx=(0,8))

        # Lista de equipos pendientes encontrados
        self._ot_var = tk.StringVar()
        self._ot_combo = ttk.Combobox(row_ot, textvariable=self._ot_var,
                                       width=40, state="readonly", font=FONT)
        self._ot_combo.pack(side="left", padx=(0,6))
        self._ot_combo.bind("<<ComboboxSelected>>", self._on_equipo_sel)
        tk.Button(row_ot, text="✓ Cargar", command=lambda: self._on_equipo_sel(None),
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="left")

        self._pendientes_lista = []

        # Separador
        tk.Frame(f, bg=BG3, height=1).pack(fill="x", padx=10, pady=4)

        # ── Carga desde JSON local (respaldo) ──
        hdr2 = tk.Frame(f, bg=BG, pady=2); hdr2.pack(fill="x", padx=14)
        tk.Label(hdr2, text="O cargar desde archivo JSON local:",
                 bg=BG, fg=TEXT2, font=("Segoe UI",8,"italic")).pack(side="left")

        row = tk.Frame(f, bg=BG); row.pack(fill="x", padx=14, pady=4)
        self.json_path = tk.StringVar()
        _entry(row, self.json_path, 40).pack(side="left", padx=(0, 8))
        tk.Button(row, text="📂 Seleccionar JSON...", command=self._cargar_json,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")

        self.lbl_json = tk.Label(f, text="Sin datos cargados", bg=BG, fg=TEXT2, font=FONT)
        self.lbl_json.pack(anchor="w", padx=14)

        s2 = _seccion(f, "Datos del equipo")
        s2.pack(fill="x", padx=10)
        grid = tk.Frame(s2, bg=BG); grid.pack(fill="x", padx=8, pady=4)

        self._ev = {}
        campos = [
            ("eq_ot",      "N° OT:",              30),
            ("eq_cert",    "Cod. Certificado:",   22),
            ("eq_desc",    "Descripcion:",        42),
            ("eq_marca",   "Marca:",              18),
            ("eq_modelo",  "Modelo:",             18),
            ("eq_serie",   "N° Serie:",           18),
            ("eq_codigo",  "ID/Codigo:",          18),
            ("eq_guia",    "N° Guia:",            18),
            ("eq_cliente", "Cliente:",            40),
            ("eq_ruc",     "RUC:",                16),
            ("eq_dir",     "Direccion:",          50),
        ]
        for i, (key, lbl, w) in enumerate(campos):
            r, c = divmod(i, 2)
            frm = tk.Frame(grid, bg=BG)
            frm.grid(row=r, column=c, sticky="w", padx=6, pady=2)
            tk.Label(frm, text=lbl, bg=BG, fg=TEXT2, font=FONT, width=17, anchor="e").pack(side="left")
            var = tk.StringVar()
            self._ev[key] = var
            _entry(frm, var, w).pack(side="left")

    def _buscar_por_ot(self):
        """Busca equipos directamente desde tabla services en Supabase."""
        ot = self._ot_buscar.get().strip()
        if not ot:
            messagebox.showwarning("Aviso", "Ingresa un numero de OT"); return
        self.lbl_json.config(text="Buscando en Supabase...", fg=TEXT2)
        self.update_idletasks()
        try:
            # Leer directamente de services
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
                self.lbl_json.config(text="Sin equipos en la OT: {}".format(ot), fg="#f59e0b")
                return
            # Guardar servicio y equipos
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
            self.lbl_json.config(text="Error: {}".format(str(e)[:80]), fg="#ef4444")

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
        """Marca el equipo pendiente como completado en Supabase."""
        if not hasattr(self, "_pendiente_id") or not self._pendiente_id: return
        url = "{}/rest/v1/calibraciones_pendientes?id=eq.{}".format(SUPABASE_URL, self._pendiente_id)
        body = json.dumps({"estado": "completado", "codigo_certificado": codigo_cert}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PATCH",
            headers={"apikey": SUPABASE_KEY,
                     "Authorization": "Bearer " + SUPABASE_KEY,
                     "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except:
            pass

    def _cargar_json(self):
        path = filedialog.askopenfilename(
            title="Seleccionar JSON de configuracion",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8") as fp:
                self.cfg_eq = json.load(fp)
            self.json_path.set(path)
            eq  = self.cfg_eq.get("equipo", self.cfg_eq)
            cli = self.cfg_eq.get("cliente", {})
            self._ev["eq_ot"].set(self.cfg_eq.get("ot_number", ""))
            self._ev["eq_cert"].set(eq.get("codigo_certificado", ""))
            self._ev["eq_desc"].set(eq.get("descripcion", ""))
            self._ev["eq_marca"].set(eq.get("marca", ""))
            self._ev["eq_modelo"].set(eq.get("modelo", ""))
            self._ev["eq_serie"].set(eq.get("nro_serie", ""))
            self._ev["eq_codigo"].set(eq.get("id_equipo", ""))
            self._ev["eq_guia"].set(eq.get("nro_guia", ""))
            self._ev["eq_cliente"].set(self.cfg_eq.get("client", "") or cli.get("nombre", ""))
            self._ev["eq_ruc"].set(self.cfg_eq.get("ruc", "") or cli.get("ruc", ""))
            self._ev["eq_dir"].set(self.cfg_eq.get("direccion_fiscal", "") or cli.get("direccion", ""))
            self.lbl_json.config(text="OK: " + os.path.basename(path), fg=ACC)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── TAB INSTRUMENTO ───────────────────────────────────────
    def _tab_instrumento(self, f):
        s = _seccion(f, "Parametros del instrumento"); s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        self.inst_res = NumField(frm, "Resolucion (mm):", "0.01", width=10)
        self.inst_res.pack(anchor="w", pady=2)

        tk.Label(frm, text="Tipo:", bg=BG, fg=TEXT2, font=FONT).pack(anchor="w", pady=(6, 0))
        self.inst_tipo = tk.StringVar(value="Digital")
        for v in ["Digital", "Analogico"]:
            tk.Radiobutton(frm, text=v, variable=self.inst_tipo, value=v,
                           bg=BG, fg=TEXT, selectcolor=BG3, activebackground=BG,
                           font=FONT).pack(anchor="w")

        self.inst_m = NumField(frm, "N° subdivisiones m (solo analogico):", "2", width=6)
        self.inst_m.pack(anchor="w", pady=2)

        s2 = _seccion(f, "Rango de calibracion"); s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=6)
        self.rango_min = NumField(frm2, "Rango minimo (mm):", "0", width=10)
        self.rango_min.pack(anchor="w", pady=2)
        self.rango_max = NumField(frm2, "Rango maximo (mm):", "200", width=10)
        self.rango_max.pack(anchor="w", pady=2)

        s3 = _seccion(f, "Bloque patron (desde Supabase)"); s3.pack(fill="x", padx=10)
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

        # Campos de solo lectura que se autocompletan
        self.pat_cert = StrField(frm3, "N° Certificado:", width=24)
        self.pat_cert.pack(anchor="w", pady=2)
        self.pat_vig  = StrField(frm3, "Vigencia:", width=14)
        self.pat_vig.pack(anchor="w", pady=2)
        self.pat_U    = NumField(frm3, "Incertidumbre U (mm):", "0.0001", width=10)
        self.pat_U.pack(anchor="w", pady=2)
        self.pat_k    = NumField(frm3, "Factor k:", "2", width=6)
        self.pat_k.pack(anchor="w", pady=2)

        self.lbl_pat = tk.Label(frm3, text="", bg=BG, fg=TEXT2, font=("Segoe UI",8,"italic"))
        self.lbl_pat.pack(anchor="w", pady=2)

        # Cargar al inicio
        self._cargar_patrones()

    # ── TAB CONDICIONES ───────────────────────────────────────
    def _tab_condiciones(self, f):
        for momento in ["inicio", "fin"]:
            s = _seccion(f, "Condiciones al {}".format(momento))
            s.pack(fill="x", padx=10)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=5)
            t = NumField(frm, "Temperatura (C):", "20.0", width=8)
            t.pack(anchor="w", pady=2)
            h = NumField(frm, "Humedad (%HR):", "50.0", width=8)
            h.pack(anchor="w", pady=2)
            setattr(self, "cond_{}_t".format(momento), t)
            setattr(self, "cond_{}_h".format(momento), h)

        s2 = _seccion(f, "Error de referencia inicial (I) - seccion 10.1.1")
        s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=5)
        tk.Label(frm2, text="3 lecturas con instrumento cerrado (mm):", bg=BG, fg=TEXT2, font=FONT).pack(anchor="w")
        self.err_ini = []
        for i in range(3):
            c = NumField(frm2, "  Lectura {}:".format(i+1), "0.0", width=10)
            c.pack(anchor="w", pady=1)
            self.err_ini.append(c)

    # ── TAB MEDICIONES ────────────────────────────────────────
    def _tab_mediciones(self, f):
        tk.Button(f, text="Generar campos de medicion",
                  command=self._gen_meds,
                  bg=ACC, fg="#000", font=FONTB, relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(pady=8)

        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._meds_inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=self._meds_inner, anchor="nw")
        self._meds_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def _gen_meds(self):
        for w in self._meds_inner.winfo_children():
            w.destroy()
        self._campos_meds = []
        try:
            rmin = self.rango_min.get(); rmax = self.rango_max.get()
        except:
            rmin, rmax = 0, 200
        pts = puntos_nominales(rmin, rmax, CONFIG["n_puntos"])
        for i, nom in enumerate(pts):
            s = _seccion(self._meds_inner, "PUNTO {}  |  {:.3f} mm".format(i+1, nom))
            s.pack(fill="x", padx=6, pady=2)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=4)
            corr = NumField(frm, "Correccion bloque cert. (mm):", "0.0", width=10)
            corr.pack(anchor="w", pady=1)
            tb   = NumField(frm, "Temp. bloque/amb. (C):", "20.0", width=8)
            tb.pack(anchor="w", pady=1)
            lecs = []
            for j, pos in enumerate(["superior", "central", "inferior"]):
                c = NumField(frm, "  Lectura {} (mm):".format(pos), "{:.3f}".format(nom), width=10)
                c.pack(anchor="w", pady=1)
                lecs.append(c)
            ti = NumField(frm, "Temp. instrumento/amb. (C):", "20.0", width=8)
            ti.pack(anchor="w", pady=1)
            self._campos_meds.append({
                "nominal": nom, "corr": corr,
                "T_bloque": tb, "lecturas": lecs, "T_inst": ti
            })

    def _cargar_patrones(self):
        """Carga patrones activos desde Supabase."""
        try:
            self.lbl_pat.config(text="Cargando patrones...", fg=TEXT2)
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
                self.lbl_pat.config(text="Sin patrones en Supabase — ingresa uno en la pestana Patrones", fg="#f59e0b")
        except Exception as e:
            self.lbl_pat.config(text="Error al cargar: {}".format(str(e)[:50]), fg="#ef4444")

    def _on_patron_sel(self, event):
        """Autocompleta campos al seleccionar patron."""
        idx = self._combo_patron.current()
        if idx < 0 or idx >= len(self._patrones_lista): return
        p = self._patrones_lista[idx]
        self.pat_cert.set(p.get("certificado",""))
        self.pat_vig.set(str(p.get("vigencia","")) if p.get("vigencia") else "")
        self.pat_U.set(p.get("u_mm", 0.0001))
        self.pat_k.set(p.get("k", 2))

    # ── TAB PATRONES ──────────────────────────────────────────
    def _tab_patrones(self, f):
        """Pestana de gestion de patrones — requiere password admin."""
        self._admin_desbloqueado = False

        # Panel de login admin
        self._frm_admin_lock = tk.Frame(f, bg=BG)
        self._frm_admin_lock.pack(fill="both", expand=True)

        tk.Label(self._frm_admin_lock, text="", bg=BG).pack(pady=20)
        tk.Label(self._frm_admin_lock,
                 text="Gestion de Patrones",
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

        # Panel de gestion (oculto hasta autenticacion)
        self._frm_admin_panel = tk.Frame(f, bg=BG)

        hdr = tk.Frame(self._frm_admin_panel, bg=BG3, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Gestion de Patrones de Calibracion",
                 bg=BG3, fg=ACC, font=FONTB).pack(side="left")
        tk.Button(hdr, text="Cerrar sesion admin",
                  command=self._cerrar_admin,
                  bg=BG2, fg=TEXT2, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="right", padx=8)

        frm_add = tk.Frame(self._frm_admin_panel, bg=BG)
        frm_add.pack(fill="x", padx=14, pady=8)

        self._pnom  = StrField(frm_add, "Nombre:",        width=35); self._pnom.pack(anchor="w",  pady=2)
        self._pinst = StrField(frm_add, "Instrumento:",   width=35); self._pinst.pack(anchor="w", pady=2)
        self._pinst.set("Bloques patron de longitud (gauge blocks)")
        self._pcert = StrField(frm_add, "N° Certificado:", width=20); self._pcert.pack(anchor="w", pady=2)
        self._pvig  = StrField(frm_add, "Vigencia (aaaa-mm-dd):", width=14); self._pvig.pack(anchor="w", pady=2)
        self._pU    = NumField(frm_add, "U (mm):", "0.0001", width=10); self._pU.pack(anchor="w", pady=2)
        self._pk    = NumField(frm_add, "Factor k:", "2", width=6);     self._pk.pack(anchor="w", pady=2)

        tk.Button(frm_add, text="+ Agregar patron",
                  command=self._agregar_patron,
                  bg=ACC, fg="#000", font=FONTB, relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(anchor="w", pady=8)

        _seccion(self._frm_admin_panel, "Patrones registrados").pack(fill="x", padx=10)

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
            messagebox.showwarning("Aviso", "El nombre del patron es obligatorio")
            return
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
            tk.Button(row, text="✕ Eliminar",
                      command=lambda i=pid, n=p.get("nombre",""): self._eliminar_patron(i, n),
                      bg="rgba(239,68,68,.1)", fg="#ef4444", font=FONT,
                      relief="flat", padx=6, cursor="hand2").pack(side="left", padx=4, pady=4)

    def _toggle_patron(self, pid, activo_actual):
        nuevo = not activo_actual
        url = "{}/rest/v1/patrones?id=eq.{}".format(SUPABASE_URL, pid)
        body = json.dumps({"activo": nuevo}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PATCH",
            headers={"apikey": SUPABASE_KEY,
                     "Authorization": "Bearer " + SUPABASE_KEY,
                     "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self._refrescar_lista_patrones()
            self._cargar_patrones()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _eliminar_patron(self, pid, nombre):
        if not messagebox.askyesno("Confirmar", "Eliminar patron: {}?".format(nombre)):
            return
        ok = _supabase_delete("patrones", pid)
        if ok:
            self._refrescar_lista_patrones()
            self._cargar_patrones()
        else:
            messagebox.showerror("Error", "No se pudo eliminar")

        for w in self._meds_inner.winfo_children():
            w.destroy()
        self._campos_meds = []
        try:
            rmin = self.rango_min.get(); rmax = self.rango_max.get()
        except:
            rmin, rmax = 0, 200
        pts = puntos_nominales(rmin, rmax, CONFIG["n_puntos"])

        for i, nom in enumerate(pts):
            s = _seccion(self._meds_inner, "PUNTO {}  |  {:.3f} mm".format(i+1, nom))
            s.pack(fill="x", padx=6, pady=2)
            frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=4)

            corr = NumField(frm, "Correccion bloque cert. (mm):", "0.0", width=10)
            corr.pack(anchor="w", pady=1)
            tb   = NumField(frm, "Temp. bloque/amb. (C):", "20.0", width=8)
            tb.pack(anchor="w", pady=1)

            lecs = []
            for j, pos in enumerate(["superior", "central", "inferior"]):
                c = NumField(frm, "  Lectura {} (mm):".format(pos), "{:.3f}".format(nom), width=10)
                c.pack(anchor="w", pady=1)
                lecs.append(c)

            ti = NumField(frm, "Temp. instrumento/amb. (C):", "20.0", width=8)
            ti.pack(anchor="w", pady=1)

            self._campos_meds.append({
                "nominal": nom, "corr": corr,
                "T_bloque": tb, "lecturas": lecs, "T_inst": ti
            })

    # ── TAB ERRORES ───────────────────────────────────────────
    def _tab_errores(self, f):
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        tk.Label(inner, text="  Nota: bloque patron precargado con rango maximo — editar si usaste otro.",
                 bg=BG, fg=TEXT2, font=("Segoe UI",8,"italic")).pack(anchor="w", padx=12, pady=(6,0))
        tk.Button(inner, text="Precargar rango maximo en todos",
                  command=self._precargar_bloques_err,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, pady=3, cursor="hand2"
                  ).pack(anchor="w", padx=12, pady=4)

        s = _seccion(inner, "Errores dimensionales seccion 10.1.2-10.1.7")
        s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        def fila(parent, lbl):
            row = tk.Frame(parent, bg=BG); row.pack(anchor="w", pady=3)
            tk.Label(row, text=lbl, bg=BG, fg=TEXT2, font=FONT, width=36, anchor="w").pack(side="left")
            val = NumField(row, "Valor (µm):", "0.0", width=7); val.pack(side="left", padx=(0,8))
            bp  = NumField(row, "Bloque patron (mm):", "200.0", width=8); bp.pack(side="left")
            return val, bp

        self.err_E,   self.err_E_bp   = fila(frm, "E  - Contacto sup. parcial:")
        self.err_SEI, self.err_SEI_bp = fila(frm, "S_EI - Cambio escala ext-int:")
        self.err_SEP, self.err_SEP_bp = fila(frm, "S_EP - Cambio escala ext-prof:")
        self.err_L,   self.err_L_bp   = fila(frm, "L  - Contacto lineal:")
        self.err_J,   self.err_J_bp   = fila(frm, "J  - Contacto sup. completa:")
        self.err_K,   self.err_K_bp   = fila(frm, "K  - Cruce sup. interiores:")

        s2 = _seccion(inner, "R - Repetibilidad (5 lecturas en mm)")
        s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=6)

        row_r = tk.Frame(frm2, bg=BG); row_r.pack(anchor="w", pady=2)
        tk.Label(row_r, text="Bloque patron usado para R (mm):", bg=BG, fg=TEXT2, font=FONT).pack(side="left", padx=(0,6))
        self.err_R_bp = NumField(row_r, "", "200.0", width=8); self.err_R_bp.pack(side="left")

        self.err_R = []
        for i in range(CONFIG["n_repeticiones"]):
            c = NumField(frm2, "  Lectura R{} (mm):".format(i+1), "0.0", width=10)
            c.pack(anchor="w", pady=1)
            self.err_R.append(c)

    def _precargar_bloques_err(self):
        try:
            rmax = self.rango_max.get()
        except:
            rmax = 200.0
        for bp in [self.err_E_bp, self.err_SEI_bp, self.err_SEP_bp,
                   self.err_L_bp, self.err_J_bp, self.err_K_bp, self.err_R_bp]:
            bp.set(rmax)

    def _tab_generar(self, f):
        s = _seccion(f, "Datos del certificado"); s.pack(fill="x", padx=10)
        frm = tk.Frame(s, bg=BG); frm.pack(fill="x", padx=8, pady=6)

        self.fecha_cal = StrField(frm, "Fecha calibracion (aaaa-mm-dd):",
                                   datetime.date.today().strftime("%Y-%m-%d"), width=14)
        self.prox_cal  = StrField(frm, "Proxima calibracion:", "A solicitud del usuario", width=28)
        self.resp_nom  = StrField(frm, "Nombre responsable tecnico:", "", width=30)
        self.resp_reg  = StrField(frm, "Registro CFP:", "", width=14)
        for w in [self.fecha_cal, self.prox_cal, self.resp_nom, self.resp_reg]:
            w.pack(anchor="w", pady=2)

        s2 = _seccion(f, "Destino del PDF"); s2.pack(fill="x", padx=10)
        frm2 = tk.Frame(s2, bg=BG); frm2.pack(fill="x", padx=8, pady=5)
        self.pdf_dest = tk.StringVar()
        _entry(frm2, self.pdf_dest, 50).pack(side="left", padx=(0, 6))
        tk.Button(frm2, text="Elegir carpeta...", command=self._elegir_carpeta,
                  bg=BG3, fg=ACC, font=FONT, relief="flat", padx=8, cursor="hand2"
                  ).pack(side="left")

        tk.Button(f, text="  GENERAR CERTIFICADO PDF  ",
                  command=lambda: threading.Thread(target=self._generar, daemon=True).start(),
                  bg=ACC, fg="#000", font=("Segoe UI", 12, "bold"),
                  relief="flat", padx=18, pady=8, cursor="hand2").pack(pady=12)

        self.log = scrolledtext.ScrolledText(f, height=11, bg=BG2, fg=TEXT,
                                              font=("Consolas", 9), relief="flat",
                                              insertbackground=ACC)
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    def _elegir_carpeta(self):
        folder = filedialog.askdirectory(title="Seleccionar carpeta de destino")
        if folder:
            cod = self._ev["eq_cert"].get() or "certificado"
            cod = cod.replace("/", "-").replace("\\", "-")
            self.pdf_dest.set(os.path.join(folder, "certificado_{}.pdf".format(cod)))

    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.update_idletasks()

    def _generar(self):
        self.log.delete("1.0", "end")
        self._log("Iniciando generacion del certificado...")
        try:
            tipo = self.inst_tipo.get()
            m    = 2 if tipo == "Digital" else int(self.inst_m.get())
            inst = {"resolucion": self.inst_res.get(), "tipo": tipo, "m": m}

            rmin = self.rango_min.get(); rmax = self.rango_max.get()
            self._log("  Rango: {} - {} mm".format(rmin, rmax))

            # Obtener nombre e instrumento del patron seleccionado
            idx_pat = self._combo_patron.current()
            pat_nombre = ""
            pat_instrumento = "Bloques patron de longitud (gauge blocks)"
            if idx_pat >= 0 and idx_pat < len(self._patrones_lista):
                p_sel = self._patrones_lista[idx_pat]
                pat_nombre = p_sel.get("nombre","")
                pat_instrumento = p_sel.get("instrumento","Bloques patron de longitud (gauge blocks)")

            patron = {
                "certificado": self.pat_cert.get(),
                "vigencia":    self.pat_vig.get(),
                "U":           self.pat_U.get(),
                "k":           self.pat_k.get(),
                "nombre":      pat_nombre,
                "instrumento": pat_instrumento,
            }

            c_ini = {"temperatura": self.cond_inicio_t.get(), "humedad": self.cond_inicio_h.get()}
            c_fin = {"temperatura": self.cond_fin_t.get(),    "humedad": self.cond_fin_h.get()}

            err_inicial = [c.get() for c in self.err_ini]

            if not self._campos_meds:
                messagebox.showwarning("Aviso", "Genera primero los campos en la pestana Mediciones")
                return

            mediciones = []
            for dp in self._campos_meds:
                nom  = dp["nominal"]
                corr = dp["corr"].get()
                LBP  = nom + corr
                lecs = [c.get() for c in dp["lecturas"]]
                mediciones.append({
                    "nominal": nom, "corr_cert": corr, "LBP": LBP,
                    "T_bloque": dp["T_bloque"].get(),
                    "T_inst":   dp["T_inst"].get(),
                    "lecturas": lecs,
                })

            R_lecs = [c.get() for c in self.err_R]
            R_um = _s(R_lecs) * 1000 if len(R_lecs) > 1 else 0.0
            errores_dim = {
                "E":      self.err_E.get(),
                "R_lecs": R_lecs, "R_um": R_um,
                "SEI":    self.err_SEI.get(),
                "SEP":    self.err_SEP.get(),
                "L":      self.err_L.get(),
                "J":      self.err_J.get(),
                "K":      self.err_K.get(),
                "bp_E":   self.err_E_bp.get(),
                "bp_R":   self.err_R_bp.get(),
                "bp_SEI": self.err_SEI_bp.get(),
                "bp_SEP": self.err_SEP_bp.get(),
                "bp_L":   self.err_L_bp.get(),
                "bp_J":   self.err_J_bp.get(),
                "bp_K":   self.err_K_bp.get(),
            }

            self._log("  Calculando GUM...")
            res, tramos, comps = calcular_todo(mediciones, inst, patron, errores_dim, c_ini, c_fin)

            cod = self._ev["eq_cert"].get() or "cert"
            cfg_eq = {
                "codigo_certificado": cod,
                "descripcion":  self._ev["eq_desc"].get(),
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
                pdf_dest = os.path.join(carpeta, "certificado_{}.pdf".format(cod.replace("/", "_")))
                self.pdf_dest.set(pdf_dest)

            carpeta_pdf = os.path.dirname(os.path.abspath(pdf_dest))
            ruta_img    = os.path.join(carpeta_pdf, "_grafico_tmp.png")

            self._log("  Generando grafico...")
            _grafico(res, ruta_img)

            self._log("  Construyendo PDF...")
            generar_pdf(
                cfg_eq, inst, patron, errores_dim, c_ini, c_fin,
                res, tramos, comps, err_inicial,
                pdf_dest, ruta_img,
                fecha_cal=self.fecha_cal.get(),
                total_pags=3,
                responsable_nombre=self.resp_nom.get(),
                responsable_reg=self.resp_reg.get(),
                proxima_calibracion=self.prox_cal.get(),
            )

            if os.path.exists(ruta_img):
                os.remove(ruta_img)

            self._log("\nPDF generado exitosamente:")
            self._log("  " + pdf_dest)
            self._log("\n-- Resumen de resultados --")
            for r in res:
                self._log("  L={:.3f} mm | Error={:.2f} um | U={:.2f} um".format(
                    r["nominal"], r["error_um"], r["U_exp_um"]))

            # ── GUARDAR REGISTRO COMPLETO ──────────────────────────
            registro = {
                "codigo":            cod,
                "ot_number":         self._ev["eq_ot"].get(),
                "magnitud":          "longitud",
                "equipo":            self._ev["eq_desc"].get(),
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
                "rango_min_mm":      self.rango_min.get(),
                "rango_max_mm":      self.rango_max.get(),
                "temp_ini":          c_ini["temperatura"],
                "temp_fin":          c_fin["temperatura"],
                "hr_ini":            c_ini["humedad"],
                "hr_fin":            c_fin["humedad"],
                "error_ini_um":      round(_media(err_inicial) * 1000, 4),
                "patron_cert":       patron["certificado"],
                "patron_vigencia":   patron["vigencia"],
                "patron_U_mm":       patron["U"],
                "patron_k":          patron["k"],
                "err_E_um":          errores_dim["E"],
                "err_R_um":          errores_dim["R_um"],
                "err_SEI_um":        errores_dim["SEI"],
                "err_SEP_um":        errores_dim["SEP"],
                "err_L_um":          errores_dim["L"],
                "err_J_um":          errores_dim["J"],
                "err_K_um":          errores_dim["K"],
                "resultados_json":   [
                    {
                        "nominal_mm":  r["nominal"],
                        "LBP_mm":      r["LBP"],
                        "media_mm":    r["media"],
                        "error_um":    round(r["error_um"], 4),
                        "error_mm":    round(r["error_mm"], 6),
                        "U_exp_um":    round(r["U_exp_um"], 4),
                        "U_exp_mm":    round(r["U_exp_mm"], 6),
                        "lecturas":    r["lecturas"],
                        "T_bloque":    r["T_bloque"],
                        "T_inst":      r["T_inst"],
                    }
                    for r in res
                ],
                "ruta_pdf":          pdf_dest,
                "observaciones":     "",
            }

            # 1) JSON local de respaldo
            ruta_registro = os.path.join(
                carpeta_pdf,
                "registro_{}.json".format(cod.replace("/", "_").replace("\\", "_"))
            )
            self._log("\nGuardando registro local...")
            guardar_registro_json(ruta_registro, registro)
            self._log("  " + ruta_registro)

            # 2) Supabase
            self._log("Subiendo a Supabase...")
            ok, resp = _supabase_upsert("certificados", registro)
            if ok:
                self._log("  OK - registro guardado en Supabase")
            else:
                self._log("  AVISO Supabase: " + resp[:120])

            # Abrir PDF automaticamente
            try:
                import subprocess
                subprocess.Popen(['start', '', pdf_dest], shell=True)
            except:
                pass

            messagebox.showinfo("Exito",
                "PDF generado:\n{}\n\nRegistro guardado:\n{}".format(pdf_dest, ruta_registro))

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
        self.geometry("340x220")
        self._center()
        self._autenticado = False
        self._build()

    def _center(self):
        self.update_idletasks()
        w, h = 340, 220
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry("{}x{}+{}+{}".format(w, h, x, y))

    def _build(self):
        tk.Label(self, text="METROMECANICA", bg="#1a1a2e", fg="#00d4aa",
                 font=("Segoe UI", 13, "bold")).pack(pady=(24, 2))
        tk.Label(self, text="Calibracion Pie de Rey", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(pady=(0, 18))

        frm = tk.Frame(self, bg="#1a1a2e")
        frm.pack()
        tk.Label(frm, text="Contrasena:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="e", padx=(0,6))
        self._pwd = tk.StringVar()
        e = tk.Entry(frm, textvariable=self._pwd, show="*", width=18,
                     bg="#16213e", fg="#e0e0e0", insertbackground="#00d4aa",
                     relief="flat", font=("Segoe UI", 10),
                     highlightthickness=1, highlightbackground="#0f3460",
                     highlightcolor="#00d4aa")
        e.grid(row=0, column=1)
        e.focus()
        e.bind("<Return>", lambda ev: self._verificar())

        self._lbl_err = tk.Label(self, text="", bg="#1a1a2e", fg="#e94560",
                                  font=("Segoe UI", 8))
        self._lbl_err.pack(pady=6)

        tk.Button(self, text="Ingresar", command=self._verificar,
                  bg="#00d4aa", fg="#000", font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=20, pady=5, cursor="hand2").pack()

    def _verificar(self):
        import hashlib
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
    app = CalApp()
    app.mainloop()
