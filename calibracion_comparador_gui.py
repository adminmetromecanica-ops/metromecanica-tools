"""
=============================================================
  METROMECANICA — Calibración de Comparadores / Relojes
  Procedimiento: PC-014 INACAL | ISO/IEC 17025:2017
  F-LLA-002
  Requiere: pip install reportlab
=============================================================
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math, json, os
from datetime import datetime, date

# ── reportlab (PDF) ──────────────────────────────────────────
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable, PageBreak)
    from reportlab.lib import colors
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

# ─────────────────────────────────────────────────────────────
#  COLORES / FUENTES
# ─────────────────────────────────────────────────────────────
C = {
    "fondo":    "#1a1d2e", "panel":   "#22263a", "borde":   "#2e3350",
    "acento":   "#00bcd4", "acento2": "#f0a500", "texto":   "#e0e6f0",
    "texto2":   "#8090b0", "ok":      "#4caf50", "error":   "#f44336",
    "entrada":  "#181b2a", "enc":     "#0d1117", "resalt":  "#263045",
}
FN  = ("Consolas", 10)
FNS = ("Consolas", 9)
FNB = ("Consolas", 11, "bold")
FNT = ("Consolas", 14, "bold")

# ─────────────────────────────────────────────────────────────
#  RANGOS PREDEFINIDOS
# ─────────────────────────────────────────────────────────────
RANGOS = {
    "0–1 mm (0,001 mm)":   {"un":"mm","rango":1.0,  "res":0.001,
        "pts":[0,0.1,0.2,0.3,0.5,0.7,1.0]},
    "0–3 mm (0,01 mm)":    {"un":"mm","rango":3.0,  "res":0.01,
        "pts":[0,0.5,1.0,1.5,2.0,2.5,3.0]},
    "0–5 mm (0,01 mm)":    {"un":"mm","rango":5.0,  "res":0.01,
        "pts":[0,0.5,1.0,2.0,3.0,4.0,5.0]},
    "0–10 mm (0,01 mm)":   {"un":"mm","rango":10.0, "res":0.01,
        "pts":[0,0.5,1.0,1.1,2.0,3.0,4.0,5.0,7.0,9.0,10.0]},
    "0–25 mm (0,01 mm)":   {"un":"mm","rango":25.0, "res":0.01,
        "pts":[0,2.5,5.0,7.5,10.0,12.5,15.0,17.5,20.0,22.5,25.0]},
    "0–50 mm (0,01 mm)":   {"un":"mm","rango":50.0, "res":0.01,
        "pts":[0,5,10,15,20,25,30,35,40,45,50]},
    "0–0,5\" (0,001\")":   {"un":"in","rango":0.5,  "res":0.001,
        "pts":[0,0.05,0.10,0.15,0.20,0.30,0.40,0.50]},
    "0–1\" (0,001\")":     {"un":"in","rango":1.0,  "res":0.001,
        "pts":[0,0.10,0.20,0.30,0.40,0.50,0.60,0.80,1.00]},
    "0–2\" (0,001\")":     {"un":"in","rango":2.0,  "res":0.001,
        "pts":[0,0.20,0.40,0.60,0.80,1.00,1.20,1.50,2.00]},
    "Personalizado":        {"un":"mm","rango":10.0, "res":0.01,"pts":[]},
}

# ─────────────────────────────────────────────────────────────
#  UTILIDADES
# ─────────────────────────────────────────────────────────────
def pf(s):
    if s is None: return None
    try:    return float(str(s).strip().replace(",","."))
    except: return None

def fm(v, d=4):
    if v is None: return "—"
    return f"{v:.{d}f}".replace(".",",")

# ─────────────────────────────────────────────────────────────
#  MOTOR GUM
# ─────────────────────────────────────────────────────────────
class GUM:
    def __init__(self, p):
        self.p = p

    def _u1(self):
        lecs = self.p["lecs_rep"]
        n = len(lecs)
        if n < 2: return 0.0
        m = sum(lecs)/n
        s = math.sqrt(sum((x-m)**2 for x in lecs)/(n-1))
        return s/math.sqrt(n)

    def _u2(self):
        U = self.p["UL_BP"]; k = self.p["k_BP"]
        u_bp = U/k
        L = self.p["L_mm"]; g = self.p["grado"]
        if g in ("K","0","K/0"):
            Ud = 0.02e-3 + 0.25e-6*L
        else:
            Ud = 0.05e-3 + 0.5e-6*L
        u_der = Ud/math.sqrt(3)
        return math.sqrt(u_bp**2 + u_der**2)

    def _u3(self):
        th = math.radians(self.p["theta"])
        dI = self.p["L_mm"]*(1-math.cos(th))
        return dI/(2*math.sqrt(3))

    def _u4(self):
        return self.p["res"]/(10*math.sqrt(3))

    def _u5(self):
        return self.p["planitud"]/math.sqrt(3)

    def _u6(self):
        P = self.p["P"]; D = self.p["D"]
        if P<=0 or D<=0: return 0.0
        dI = 4.4e-4*(P**(2/3))*((1/D)**(1/3))
        return dI/(2*math.sqrt(3))

    def _u7(self):
        ua = math.sqrt(2)*1e-6/math.sqrt(3)
        dt = max(abs(self.p["dt1"]), abs(self.p["dt2"]))
        return self.p["L_mm"]*dt*ua

    def _u8(self):
        Uc=self.p.get("Ut_cert",0.02); kt=self.p.get("k_t",2.0)
        dt=max(abs(self.p["dt1"]),abs(self.p["dt2"]))
        d=self.p.get("d_t",0.01); Ud=self.p.get("Ut_der",0.02)
        u_dt=math.sqrt((Uc/kt)**2+(dt/math.sqrt(3))**2+
                       (d/(2*math.sqrt(3)))**2+(Ud/math.sqrt(3))**2)
        return self.p["L_mm"]*11.5e-6*u_dt

    def calc(self):
        u=[self._u1(),self._u2(),self._u3(),self._u4(),
           self._u5(),self._u6(),self._u7(),self._u8()]
        uc=math.sqrt(sum(x**2 for x in u))
        U=2*uc
        tot=sum(x**2 for x in u) or 1
        return {"u":u,"uc":uc,"U_mm":U,"U_um":U*1000,
                "pct":[100*x**2/tot for x in u]}

# ─────────────────────────────────────────────────────────────
#  GENERADOR PDF
# ─────────────────────────────────────────────────────────────
def generar_pdf(ruta, datos):
    if not REPORTLAB_OK:
        messagebox.showerror("Error","Instala reportlab:\n  pip install reportlab")
        return False

    doc = SimpleDocTemplate(ruta, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm)

    # estilos
    azul  = colors.HexColor("#00bcd4")
    oscuro= colors.HexColor("#0d1117")
    gris  = colors.HexColor("#8090b0")
    negro = colors.black
    verde = colors.HexColor("#2e7d32")
    rojo  = colors.HexColor("#c62828")
    blanco= colors.white
    amarillo = colors.HexColor("#f0a500")

    def sty(name,**kw):
        base = dict(fontName="Helvetica",fontSize=9,
                    textColor=negro,leading=13)
        base.update(kw)
        return ParagraphStyle(name,**base)

    S_tit  = sty("tit",  fontName="Helvetica-Bold",fontSize=13,
                         alignment=TA_CENTER, textColor=oscuro, spaceAfter=4)
    S_sub  = sty("sub",  fontName="Helvetica-Bold",fontSize=10,
                         textColor=azul, spaceAfter=2)
    S_norm = sty("norm", fontSize=9, leading=13)
    S_cent = sty("cent", fontSize=9, alignment=TA_CENTER)
    S_pie  = sty("pie",  fontSize=7, textColor=gris, alignment=TA_CENTER)
    S_obs  = sty("obs",  fontSize=8, textColor=negro, leading=12)

    def tabla_hdr(cols, data, col_widths=None, alt=True):
        t = Table([[Paragraph(str(c), sty("th",fontName="Helvetica-Bold",
                    fontSize=8,alignment=TA_CENTER,textColor=blanco))
                    for c in cols]] +
                  [[Paragraph(str(x), sty("td",fontSize=8,
                    alignment=TA_CENTER)) for x in row]
                   for row in data],
                  colWidths=col_widths)
        estilo = [
            ("BACKGROUND",(0,0),(-1,0),oscuro),
            ("TEXTCOLOR",  (0,0),(-1,0),blanco),
            ("GRID",       (0,0),(-1,-1),0.3,colors.HexColor("#cccccc")),
            ("FONTNAME",   (0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",   (0,0),(-1,-1),8),
            ("ALIGN",      (0,0),(-1,-1),"CENTER"),
            ("VALIGN",     (0,0),(-1,-1),"MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),
             [colors.HexColor("#f5f5f5"),blanco] if alt else [blanco]),
        ]
        t.setStyle(TableStyle(estilo))
        return t

    story = []

    # ── PORTADA ─────────────────────────────────────────────
    # cabecera institucional
    cab_data = [[
        Paragraph("<b>METROMECANICA INGENIERÍA Y METROLOGÍA S.A.C.</b><br/>"
                  "Laboratorio de Calibración | ISO/IEC 17025:2017<br/>"
                  "RUC: 20605421696",
                  sty("cab",fontSize=9,alignment=TA_CENTER,textColor=oscuro)),
        Paragraph("<b>CERTIFICADO DE CALIBRACIÓN</b><br/>"
                  f"N° Expediente: {datos['expediente']}<br/>"
                  f"F-LLA-002 | PC-014",
                  sty("cab2",fontSize=9,alignment=TA_CENTER,textColor=oscuro)),
    ]]
    tc = Table(cab_data, colWidths=[90*mm, 82*mm])
    tc.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),1,azul),
        ("LINEAFTER",(0,0),(0,-1),0.5,azul),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(tc)
    story.append(Spacer(1,8*mm))

    # título
    story.append(Paragraph("CALIBRACIÓN DE COMPARADORES",S_tit))
    story.append(HRFlowable(width="100%",thickness=1,color=azul))
    story.append(Spacer(1,4*mm))

    # datos del instrumento
    story.append(Paragraph("1. DATOS DEL INSTRUMENTO Y PATRÓN",S_sub))
    d = datos
    info = [
        ["Expediente",    d["expediente"],    "Fecha",       d["fecha"]],
        ["Marca",         d["marca"],         "Modelo",      d["modelo"]],
        ["N° Serie",      d["serie"],         "Rango",       d["rango"]],
        ["Resolución",    d["resolucion"],     "EMP ±",       d["emp"]],
        ["Patrón",        d["pat_codigo"],     "Certificado", d["pat_cert"]],
        ["Metrólogo",     d["metrologo"],     "Supervisor",  d["supervisor"]],
    ]
    ti = Table([[Paragraph(str(x),sty("i",fontSize=8,
                fontName="Helvetica-Bold" if i%2==0 else "Helvetica"))
                for i,x in enumerate(row)] for row in info],
               colWidths=[32*mm,48*mm,32*mm,48*mm])
    ti.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#cccccc")),
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#e3f2fd")),
        ("BACKGROUND",(2,0),(2,-1),colors.HexColor("#e3f2fd")),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(0,0),(-1,-1),"LEFT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story.append(ti)
    story.append(Spacer(1,6*mm))

    # ── ERRORES DE INDICACIÓN ──────────────────────────────
    story.append(Paragraph("2. ERRORES DE INDICACIÓN",S_sub))

    un = datos["unidad"]
    emp_v = pf(d["emp_val"]) or 0.008
    cols_err = [f"Valor Patrón\n({un})", f"Indicación\n({un})",
                "Error\n(mm)", f"EMP ±\n({un})", "Conformidad"]
    rows_err = []
    for fila in datos["errores"]:
        L = pf(fila["patron"])
        I = pf(fila["indicacion"])
        if L is None or I is None: continue
        C = pf(fila.get("corr","0")) or 0.0
        L_bp = L + C/1000
        E = (I - L_bp)*(25.4 if un=="in" else 1.0)
        conf = "✓ CONFORME" if abs(E)<=emp_v else "✗ NO CONF."
        rows_err.append([fm(L,3), fm(I,3), fm(E,4), fm(emp_v,3), conf])

    t_err = tabla_hdr(cols_err, rows_err,
                      col_widths=[34*mm,34*mm,34*mm,28*mm,32*mm])
    # colorear conformidad
    for i,row in enumerate(rows_err,1):
        color = colors.HexColor("#e8f5e9") if "✓" in row[4] \
                else colors.HexColor("#ffebee")
        t_err.setStyle(TableStyle([("BACKGROUND",(4,i),(4,i),color)]))
    story.append(t_err)
    story.append(Spacer(1,5*mm))

    # ── REPETIBILIDAD ──────────────────────────────────────
    story.append(Paragraph("3. ERROR DE REPETIBILIDAD",S_sub))
    cols_rep = ["N° Lectura", f"Indicación ({un})", "T Bloque (°C)"]
    rows_rep = []
    lecs_mm = []
    for i,fila in enumerate(datos["repetibilidad"],1):
        I = pf(fila["indicacion"])
        T = fila.get("T","20,6")
        rows_rep.append([str(i), fm(I,4) if I else "—", T])
        if I is not None:
            lecs_mm.append(I*(25.4 if un=="in" else 1.0))
    story.append(tabla_hdr(cols_rep, rows_rep,
                            col_widths=[30*mm,60*mm,60*mm]))

    if len(lecs_mm)>=2:
        n=len(lecs_mm); m=sum(lecs_mm)/n
        s=math.sqrt(sum((x-m)**2 for x in lecs_mm)/(n-1))
        u_rep=s/math.sqrt(n)
        story.append(Spacer(1,3*mm))
        story.append(Paragraph(
            f"Media: {fm(m,5)} mm  |  s(Ī) = {fm(s,5)} mm  |  "
            f"u(Ī) = {fm(u_rep,5)} mm = {fm(u_rep*1000,3)} µm",
            sty("rep",fontSize=9,fontName="Helvetica-Bold",textColor=oscuro)))
    story.append(Spacer(1,5*mm))

    # ── INCERTIDUMBRE ─────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("4. PRESUPUESTO DE INCERTIDUMBRE",S_sub))

    fuentes = [
        "Repetibilidad","Bloque patrón + deriva","Error de coseno",
        "Resolución visualizador","Planitud soporte","Deformación bloque",
        "Expansión térmica","Variación temperatura",
    ]
    distrib = ["Normal","Normal","Rectangular","Rectangular",
               "Rectangular","Rectangular","Rectangular","Rectangular"]

    gum = datos.get("gum",{})
    u_vals = gum.get("u",[0]*8)
    pcts   = gum.get("pct",[0]*8)

    cols_gum = ["N°","Fuente","Distribución",
                "u estándar (mm)","Contribución (mm)","% Part."]
    rows_gum = []
    for i,(f,dist) in enumerate(zip(fuentes,distrib)):
        u = u_vals[i] if i<len(u_vals) else 0
        p = pcts[i]   if i<len(pcts)   else 0
        rows_gum.append([str(i+1),f,dist,fm(u,6),fm(u,6),f"{p:.1f}%"])

    t_gum = tabla_hdr(cols_gum, rows_gum,
                      col_widths=[8*mm,50*mm,26*mm,28*mm,28*mm,16*mm])
    story.append(t_gum)
    story.append(Spacer(1,4*mm))

    uc  = gum.get("uc",0)
    U_m = gum.get("U_mm",0)
    U_u = gum.get("U_um",0)

    res_data = [
        ["Incertidumbre estándar combinada  uc",
         f"{fm(uc,6)} mm"],
        ["Incertidumbre expandida  U (k=2, ≈95%)",
         f"{fm(U_m,4)} mm  =  {fm(U_u,1)} µm"],
    ]
    t_res = Table([[Paragraph(r[0],sty("rk",fontSize=9,fontName="Helvetica-Bold")),
                    Paragraph(r[1],sty("rv",fontSize=10,fontName="Helvetica-Bold",
                               textColor=azul))]
                   for r in res_data], colWidths=[110*mm,52*mm])
    t_res.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),1,azul),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#cccccc")),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#e3f2fd")),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t_res)
    story.append(Spacer(1,6*mm))

    # ── OBSERVACIONES ─────────────────────────────────────
    story.append(Paragraph("5. OBSERVACIONES",S_sub))
    obs = [
        f"Ángulo considerado al utilizar el soporte para comparadores θ = {datos.get('theta','0,5')}°",
        f"Diámetro del comparador D = {datos.get('D_mm','2,5')} mm y fuerza P = {datos.get('P_N','1,8')} N "
        "(datos dados en el manual del fabricante del comparador).",
        datos.get("obs_libre",""),
    ]
    for o in obs:
        if o.strip():
            story.append(Paragraph("• "+o, S_obs))
    story.append(Spacer(1,8*mm))

    # ── FIRMAS ────────────────────────────────────────────
    firmas = [
        [Paragraph(datos["metrologo"],  sty("fm",fontSize=9,alignment=TA_CENTER)),
         Paragraph(datos["supervisor"], sty("fm",fontSize=9,alignment=TA_CENTER))],
        [Paragraph("____________________________",sty("fl",alignment=TA_CENTER)),
         Paragraph("____________________________",sty("fl",alignment=TA_CENTER))],
        [Paragraph("Metrólogo",sty("fc",fontSize=8,alignment=TA_CENTER,textColor=gris)),
         Paragraph("Supervisor",sty("fc",fontSize=8,alignment=TA_CENTER,textColor=gris))],
    ]
    tf = Table(firmas, colWidths=[85*mm,85*mm])
    tf.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER")]))
    story.append(tf)
    story.append(Spacer(1,6*mm))

    # ── PIE DE PÁGINA ─────────────────────────────────────
    story.append(HRFlowable(width="100%",thickness=0.5,color=gris))
    story.append(Paragraph(
        "F-LLA-002 | PC-014 INACAL | MetroMecánica Ingeniería y Metrología S.A.C. | "
        "ISO/IEC 17025:2017 | www.metromecanica.com.pe",
        S_pie))

    doc.build(story)
    return True

# ─────────────────────────────────────────────────────────────
#  APLICACIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calibración de Comparadores PC-014 — MetroMecánica SAC")
        self.configure(bg=C["fondo"])
        self.geometry("1260x880")
        self.minsize(1060,720)

        # estado
        self.rango_var  = tk.StringVar(value="0–10 mm (0,01 mm)")
        self.filas_err  = []
        self.filas_rep  = []
        self.gum_result = None
        self.nominal_rep= tk.StringVar(value="10")

        self._build()

    # ── LAYOUT ─────────────────────────────────────────────
    def _build(self):
        # encabezado
        enc = tk.Frame(self, bg=C["enc"], height=54)
        enc.pack(fill="x"); enc.pack_propagate(False)
        tk.Label(enc,text="⊕ METROTRACK  ·  Calibración de Comparadores  ·  PC-014",
                 font=("Consolas",14,"bold"),bg=C["enc"],fg=C["acento"]
                 ).pack(side="left",padx=20,pady=12)
        tk.Label(enc,text="MetroMecánica SAC  ·  ISO/IEC 17025",
                 font=FNS,bg=C["enc"],fg=C["acento2"]
                 ).pack(side="right",padx=20)

        # notebook
        st = ttk.Style(self); st.theme_use("clam")
        st.configure("TNotebook",background=C["fondo"],borderwidth=0)
        st.configure("TNotebook.Tab",background=C["panel"],
                     foreground=C["texto2"],font=FN,padding=[12,5])
        st.map("TNotebook.Tab",
               background=[("selected",C["acento"])],
               foreground=[("selected",C["enc"])])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both",expand=True,padx=6,pady=(3,6))

        tabs = [tk.Frame(self.nb,bg=C["fondo"]) for _ in range(5)]
        nombres = [" 1. Datos "," 2. Errores "," 3. Repetibilidad ",
                   " 4. Incertidumbre "," 5. Resultados "]
        for t,n in zip(tabs,nombres):
            self.nb.add(t,text=n)
        (self.t_datos, self.t_err, self.t_rep,
         self.t_gum,   self.t_res) = tabs

        self._tab_datos()
        self._tab_err()
        self._tab_rep()
        self._tab_gum()
        self._tab_res()

    # ── helpers ────────────────────────────────────────────
    def _scroll_frame(self, parent):
        cv = tk.Canvas(parent, bg=C["fondo"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        fr = tk.Frame(cv, bg=C["fondo"])
        wid = cv.create_window((0,0), window=fr, anchor="nw")

        def _mwheel(e):
            cv.yview_scroll(int(-1*(e.delta/120)), "units")

        def _bind_all(w):
            w.bind("<MouseWheel>", _mwheel)
            for ch in w.winfo_children():
                _bind_all(ch)

        fr.bind("<Configure>", lambda e: (
            cv.configure(scrollregion=cv.bbox("all")),
            _bind_all(fr)
        ))
        cv.bind("<Configure>", lambda e: cv.itemconfig(wid, width=e.width))
        cv.bind("<MouseWheel>", _mwheel)
        return fr

    def _sec(self, p, txt):
        f = tk.Frame(p, bg=C["fondo"])
        f.pack(fill="x", padx=20, pady=(14,3))
        tk.Label(f,text=txt,font=FNB,bg=C["fondo"],fg=C["acento2"]
                 ).pack(side="left")
        tk.Frame(f,bg=C["borde"],height=1
                 ).pack(side="left",fill="x",expand=True,padx=(8,0),pady=5)

    def _lbl_entry(self, parent, row, col, lbl, var, w=18):
        tk.Label(parent,text=lbl+":",font=FNS,bg=C["fondo"],
                 fg=C["texto2"],anchor="w",width=w
                 ).grid(row=row,column=col*2,sticky="w",padx=(0,4),pady=3)
        tk.Entry(parent,textvariable=var,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],
                 relief="flat",bd=0,width=22
                 ).grid(row=row,column=col*2+1,sticky="ew",padx=(0,18),pady=3)

    def _btn(self, parent, txt, cmd, color=None, pady=10):
        color = color or C["acento"]
        tk.Button(parent,text=txt,command=cmd,font=FNB,
                  bg=color,fg=C["enc"],
                  activebackground=C["acento2"],
                  relief="flat",padx=22,pady=pady
                  ).pack(pady=12)

    # ── TAB 1: DATOS ───────────────────────────────────────
    def _tab_datos(self):
        fr = self._scroll_frame(self.t_datos)

        self._sec(fr,"EXPEDIENTE")
        g = tk.Frame(fr,bg=C["fondo"]); g.pack(fill="x",padx=20,pady=4)
        self.ve = {}
        campos = [
            ("Expediente","exp","XXXXXX"),("Marca","marca","XXXXX"),
            ("Modelo","modelo","XXXXX"),("N° Serie","serie","XXXXX"),
            ("Fecha","fecha",str(date.today())),("Metrólogo","metrologo","XXXXX"),
            ("Supervisor","supervisor","XXXXX"),("Cliente","cliente",""),
        ]
        for i,(lbl,k,d) in enumerate(campos):
            r,c = divmod(i,2)
            v = tk.StringVar(value=d); self.ve[k]=v
            self._lbl_entry(g,r,c,lbl,v)

        self._sec(fr,"INSTRUMENTO")
        gi = tk.Frame(fr,bg=C["fondo"]); gi.pack(fill="x",padx=20,pady=4)
        tk.Label(gi,text="Rango / Resolución:",font=FNS,bg=C["fondo"],
                 fg=C["texto2"],anchor="w",width=24
                 ).grid(row=0,column=0,sticky="w",pady=4)
        cb = ttk.Combobox(gi,textvariable=self.rango_var,
                          values=list(RANGOS.keys()),state="readonly",
                          font=FN,width=26)
        cb.grid(row=0,column=1,sticky="w",padx=8,pady=4)
        cb.bind("<<ComboboxSelected>>",self._on_rango)

        tk.Label(gi,text="Intervalo indicación:",font=FNS,bg=C["fondo"],
                 fg=C["texto2"],anchor="w",width=24
                 ).grid(row=1,column=0,sticky="w",pady=4)
        self.v_intervalo = tk.StringVar(value="0 mm a 10 mm")
        tk.Entry(gi,textvariable=self.v_intervalo,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],relief="flat",bd=0,width=30
                 ).grid(row=1,column=1,sticky="w",padx=8,pady=4)

        tk.Label(gi,text="Resolución:",font=FNS,bg=C["fondo"],
                 fg=C["texto2"],anchor="w",width=24
                 ).grid(row=2,column=0,sticky="w",pady=4)
        frr=tk.Frame(gi,bg=C["fondo"]); frr.grid(row=2,column=1,sticky="w",padx=8,pady=4)
        self.v_res=tk.StringVar(value="0,01")
        tk.Entry(frr,textvariable=self.v_res,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],relief="flat",bd=0,width=12
                 ).pack(side="left")
        self.v_res_un=tk.StringVar(value="mm")
        ttk.Combobox(frr,textvariable=self.v_res_un,
                     values=["mm","in","µm"],state="readonly",font=FNS,width=5
                     ).pack(side="left",padx=6)

        tk.Label(gi,text="EMP ± :",font=FNS,bg=C["fondo"],
                 fg=C["texto2"],anchor="w",width=24
                 ).grid(row=3,column=0,sticky="w",pady=4)
        fre=tk.Frame(gi,bg=C["fondo"]); fre.grid(row=3,column=1,sticky="w",padx=8,pady=4)
        self.v_emp=tk.StringVar(value="0,008")
        tk.Entry(fre,textvariable=self.v_emp,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],relief="flat",bd=0,width=12
                 ).pack(side="left")
        self.v_emp_un=tk.StringVar(value="mm")
        ttk.Combobox(fre,textvariable=self.v_emp_un,
                     values=["mm","in","µm"],state="readonly",font=FNS,width=5
                     ).pack(side="left",padx=6)
        tk.Label(fre,text="(dato fabricante)",font=FNS,bg=C["fondo"],
                 fg=C["texto2"]).pack(side="left",padx=6)

        self._sec(fr,"PATRÓN — BLOQUES")
        gp = tk.Frame(fr,bg=C["fondo"]); gp.pack(fill="x",padx=20,pady=4)
        self.vp = {}
        campos_p = [
            ("Código patrón","pat_cod","LA 01 003"),
            ("Certificado N°","pat_cert","INACAL DM/LLA-C-013-2017"),
            ("U expandida (mm)","pat_U","0,00011"),
            ("Factor k","pat_k","2"),
            ("Grado bloques","pat_grado","K/0"),
            ("Planitud t// (mm)","pat_plan","0,0013"),
        ]
        for i,(lbl,k,d) in enumerate(campos_p):
            r,c=divmod(i,2)
            v=tk.StringVar(value=d); self.vp[k]=v
            self._lbl_entry(gp,r,c,lbl,v,w=22)

        self._sec(fr,"PARÁMETROS FÍSICOS")
        gf=tk.Frame(fr,bg=C["fondo"]); gf.pack(fill="x",padx=20,pady=4)
        self.vf={}
        for i,(lbl,k,d) in enumerate([
            ("Fuerza P (N)","P","1,8"),
            ("Diámetro D (mm)","D","2,5"),
            ("Ángulo θ soporte (°)","theta","0,5"),
        ]):
            v=tk.StringVar(value=d); self.vf[k]=v
            self._lbl_entry(gf,i,0,lbl,v)

        self._sec(fr,"TEMPERATURA")
        gt=tk.Frame(fr,bg=C["fondo"]); gt.pack(fill="x",padx=20,pady=4)
        self.vt={}
        for i,(lbl,k,d) in enumerate([
            ("T inicial (°C)","ti","20,0"),("T final (°C)","tf","20,0"),
            ("U cert. termóm. (°C)","Uc","0,02"),("k termómetro","kt","2"),
            ("Resolución termóm. (°C)","d","0,01"),("U deriva termóm. (°C)","Ud","0,02"),
        ]):
            r,c=divmod(i,2)
            v=tk.StringVar(value=d); self.vt[k]=v
            self._lbl_entry(gt,r,c,lbl,v,w=24)

        self._sec(fr,"OBSERVACIONES LIBRES")
        of=tk.Frame(fr,bg=C["fondo"]); of.pack(fill="x",padx=20,pady=4)
        self.v_obs=tk.StringVar(value="")
        tk.Entry(of,textvariable=self.v_obs,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],relief="flat",bd=0,width=70
                 ).pack(fill="x")

        # botones
        bf=tk.Frame(fr,bg=C["fondo"]); bf.pack(pady=10)
        tk.Button(bf,text="⟶  GENERAR TABLA DE ERRORES",
                  command=self._gen_tabla_err,
                  font=FNB,bg=C["acento"],fg=C["enc"],
                  activebackground=C["acento2"],
                  relief="flat",padx=22,pady=10
                  ).pack(side="left",padx=8)
        tk.Button(bf,text="📂  Importar JSON",
                  command=self._importar_json,
                  font=FN,bg=C["panel"],fg=C["texto2"],
                  activebackground=C["resalt"],
                  relief="flat",padx=14,pady=10
                  ).pack(side="left",padx=8)

    def _on_rango(self, e=None):
        cfg = RANGOS[self.rango_var.get()]
        un = cfg["un"]
        self.v_intervalo.set(f"0 {un} a {fm(cfg['rango'],3)} {un}")
        self.v_res.set(fm(cfg["res"],3))
        self.v_res_un.set(un)
        self.v_emp_un.set(un)
        self.nominal_rep.set(fm(cfg["rango"],3))
        self.v_emp.set(fm(cfg["res"]*0.8,3))

    # ── TAB 2: ERRORES ─────────────────────────────────────
    def _tab_err(self):
        self.fr_err = tk.Frame(self.t_err, bg=C["fondo"])
        self.fr_err.pack(fill="both", expand=True)

    def _gen_tabla_err(self):
        for w in self.fr_err.winfo_children(): w.destroy()
        self.filas_err.clear()
        cfg = RANGOS[self.rango_var.get()]
        puntos = cfg["pts"]; un = cfg["un"]

        fr = self._scroll_frame(self.fr_err)
        self._sec(fr,"DETERMINACIÓN DE LOS ERRORES DE INDICACIÓN")

        # temp
        tf=tk.Frame(fr,bg=C["fondo"]); tf.pack(fill="x",padx=20,pady=4)
        self.v_Terr_ini=tk.StringVar(value=self.vt["ti"].get())
        self.v_Terr_fin=tk.StringVar(value=self.vt["tf"].get())
        for lbl,v in [("T inicio (°C):",self.v_Terr_ini),
                      ("T final (°C):", self.v_Terr_fin)]:
            tk.Label(tf,text=lbl,font=FNS,bg=C["fondo"],fg=C["texto2"]
                     ).pack(side="left",padx=(0,4))
            tk.Entry(tf,textvariable=v,width=8,font=FN,
                     bg=C["entrada"],fg=C["texto"],
                     insertbackground=C["acento"],relief="flat",bd=0
                     ).pack(side="left",padx=(0,16))

        # encabezado tabla
        hdr=tk.Frame(fr,bg=C["panel"]); hdr.pack(fill="x",padx=20,pady=(10,0))
        for txt,w in [(f"Bloque\n({un})",16),("Corr. cert.\n(mm)",14),
                      (f"Indicación\n({un})",16),("T Bloque\n(°C)",12)]:
            tk.Label(hdr,text=txt,font=FNS,width=w,
                     bg=C["panel"],fg=C["acento"],
                     relief="flat",bd=0,padx=4,pady=5
                     ).pack(side="left")

        for i,p in enumerate(puntos):
            bg=C["panel"] if i%2==0 else C["resalt"]
            fila=tk.Frame(fr,bg=bg); fila.pack(fill="x",padx=20)
            v_pat=tk.StringVar(value=fm(p,3))
            v_cor=tk.StringVar(value="0,000")
            v_ind=tk.StringVar(value="")
            v_T  =tk.StringVar(value="20,4")
            for var,w in [(v_pat,16),(v_cor,14),(v_ind,16),(v_T,12)]:
                tk.Entry(fila,textvariable=var,width=w,font=FN,
                         bg=C["entrada"],fg=C["texto"],
                         insertbackground=C["acento"],relief="flat",bd=0
                         ).pack(side="left",padx=2,pady=2)
            self.filas_err.append({"patron":v_pat,"corr":v_cor,
                                   "indicacion":v_ind,"T":v_T})

        tk.Button(fr,text="⟶  CALCULAR ERRORES",
                  command=self._calc_errores,font=FN,
                  bg=C["ok"],fg=C["enc"],
                  activebackground=C["acento"],
                  relief="flat",padx=16,pady=7
                  ).pack(pady=10)

        self._sec(fr,"ERRORES CALCULADOS")
        self.fr_err_calc=tk.Frame(fr,bg=C["fondo"])
        self.fr_err_calc.pack(fill="x",padx=20)

        self.nb.select(self.t_err)

    def _calc_errores(self):
        for w in self.fr_err_calc.winfo_children(): w.destroy()
        un=RANGOS[self.rango_var.get()]["un"]
        emp=pf(self.v_emp.get()) or 0.008

        hdr=tk.Frame(self.fr_err_calc,bg=C["panel"]); hdr.pack(fill="x")
        for txt,w in [(f"Patrón ({un})",14),(f"Indicación ({un})",14),
                      ("Error (mm)",14),(f"EMP ±({un})",12),("Conformidad",14)]:
            tk.Label(hdr,text=txt,font=FNS,width=w,
                     bg=C["panel"],fg=C["acento"],pady=5
                     ).pack(side="left")

        for i,fila in enumerate(self.filas_err):
            L=pf(fila["patron"].get()); I=pf(fila["indicacion"].get())
            if L is None or I is None: continue
            Corr=pf(fila["corr"].get()) or 0.0
            L_bp=L+Corr/1000
            E=(I-L_bp)*(25.4 if un=="in" else 1.0)
            conf=abs(E)<=emp
            bg=C["panel"] if i%2==0 else C["resalt"]
            fil=tk.Frame(self.fr_err_calc,bg=bg); fil.pack(fill="x")
            for txt,w,clr in [
                (fm(L,3),14,C["texto"]),(fm(I,3),14,C["texto"]),
                (fm(E,4),14,C["texto"]),(fm(emp,3),12,C["texto2"]),
                ("✓ CONF." if conf else "✗ NO CONF.",14,
                 C["ok"] if conf else C["error"])]:
                tk.Label(fil,text=txt,font=FNS,width=w,
                         bg=bg,fg=clr,pady=4).pack(side="left",padx=2)

    # ── TAB 3: REPETIBILIDAD ───────────────────────────────
    def _tab_rep(self):
        fr=self._scroll_frame(self.t_rep)
        self._sec(fr,"ERROR DE REPETIBILIDAD")

        cfg_frm=tk.Frame(fr,bg=C["fondo"]); cfg_frm.pack(fill="x",padx=20,pady=4)
        tk.Label(cfg_frm,text="Bloque nominal:",font=FNS,bg=C["fondo"],fg=C["texto2"]
                 ).pack(side="left")
        tk.Entry(cfg_frm,textvariable=self.nominal_rep,width=10,font=FN,
                 bg=C["entrada"],fg=C["texto"],
                 insertbackground=C["acento"],relief="flat",bd=0
                 ).pack(side="left",padx=8)
        tk.Label(cfg_frm,text="N° lecturas:",font=FNS,bg=C["fondo"],fg=C["texto2"]
                 ).pack(side="left",padx=(20,0))
        self.v_nrep=tk.StringVar(value="5")
        ttk.Combobox(cfg_frm,textvariable=self.v_nrep,
                     values=["3","5","7","10"],state="readonly",
                     font=FNS,width=4).pack(side="left",padx=6)

        tf2=tk.Frame(fr,bg=C["fondo"]); tf2.pack(fill="x",padx=20,pady=4)
        self.v_Trep_ini=tk.StringVar(value="20,0")
        self.v_Trep_fin=tk.StringVar(value="20,0")
        for lbl,v in [("T inicio (°C):",self.v_Trep_ini),
                      ("T final (°C):", self.v_Trep_fin)]:
            tk.Label(tf2,text=lbl,font=FNS,bg=C["fondo"],fg=C["texto2"]
                     ).pack(side="left",padx=(0,4))
            tk.Entry(tf2,textvariable=v,width=8,font=FN,
                     bg=C["entrada"],fg=C["texto"],
                     insertbackground=C["acento"],relief="flat",bd=0
                     ).pack(side="left",padx=(0,16))

        tk.Button(fr,text="⟶  GENERAR TABLA REPETIBILIDAD",
                  command=self._gen_tabla_rep,font=FN,
                  bg=C["acento2"],fg=C["enc"],
                  activebackground=C["acento"],
                  relief="flat",padx=16,pady=7
                  ).pack(pady=10)

        self.fr_tabla_rep=tk.Frame(fr,bg=C["fondo"])
        self.fr_tabla_rep.pack(fill="x",padx=20)
        self.fr_res_rep=tk.Frame(fr,bg=C["fondo"])
        self.fr_res_rep.pack(fill="x",padx=20,pady=8)

    def _gen_tabla_rep(self):
        for w in self.fr_tabla_rep.winfo_children(): w.destroy()
        for w in self.fr_res_rep.winfo_children(): w.destroy()
        self.filas_rep.clear()
        n=int(self.v_nrep.get())
        un=RANGOS[self.rango_var.get()]["un"]

        hdr=tk.Frame(self.fr_tabla_rep,bg=C["panel"]); hdr.pack(fill="x")
        for txt,w in [(f"Bloque ({un})",14),("Lectura",8),
                      (f"Indicación ({un})",16),("T Bloque (°C)",12)]:
            tk.Label(hdr,text=txt,font=FNS,width=w,
                     bg=C["panel"],fg=C["acento"],pady=5
                     ).pack(side="left")

        for i in range(n):
            bg=C["panel"] if i%2==0 else C["resalt"]
            fila=tk.Frame(self.fr_tabla_rep,bg=bg); fila.pack(fill="x")
            v_ind=tk.StringVar(); v_T=tk.StringVar(value="20,6")
            tk.Label(fila,text=self.nominal_rep.get() if i==0 else "",
                     font=FN,width=14,bg=bg,fg=C["texto"]
                     ).pack(side="left",padx=2,pady=2)
            tk.Label(fila,text=str(i+1),font=FNS,width=8,
                     bg=bg,fg=C["texto2"]).pack(side="left",padx=2,pady=2)
            tk.Entry(fila,textvariable=v_ind,width=16,font=FN,
                     bg=C["entrada"],fg=C["texto"],
                     insertbackground=C["acento"],relief="flat",bd=0
                     ).pack(side="left",padx=2,pady=2)
            tk.Entry(fila,textvariable=v_T,width=12,font=FN,
                     bg=C["entrada"],fg=C["texto"],
                     insertbackground=C["acento"],relief="flat",bd=0
                     ).pack(side="left",padx=2,pady=2)
            self.filas_rep.append({"indicacion":v_ind,"T":v_T})

        tk.Button(self.fr_tabla_rep,text="⟶  CALCULAR REPETIBILIDAD",
                  command=self._calc_rep,font=FN,
                  bg=C["ok"],fg=C["enc"],
                  activebackground=C["acento"],
                  relief="flat",padx=16,pady=7
                  ).pack(pady=8)

    def _calc_rep(self):
        for w in self.fr_res_rep.winfo_children(): w.destroy()
        un=RANGOS[self.rango_var.get()]["un"]
        lecs=[pf(f["indicacion"].get()) for f in self.filas_rep]
        lecs=[x for x in lecs if x is not None]
        if len(lecs)<2:
            messagebox.showwarning("Datos","Ingresa al menos 2 lecturas."); return
        lecs_mm=[x*25.4 if un=="in" else x for x in lecs]
        n=len(lecs_mm); m=sum(lecs_mm)/n
        s=math.sqrt(sum((x-m)**2 for x in lecs_mm)/(n-1))
        u=s/math.sqrt(n)
        self._lecs_rep_mm=lecs_mm

        self._sec(self.fr_res_rep,"RESULTADO")
        pn=tk.Frame(self.fr_res_rep,bg=C["panel"]); pn.pack(fill="x",pady=4)
        for lbl,val in [("N",str(n)),(f"Media ({un})",
                         fm(m/25.4 if un=="in" else m,5)),
                        ("s(Ī) [mm]",fm(s,5)),
                        ("u(Ī) [mm]",fm(u,5)),
                        ("u(Ī) [µm]",fm(u*1000,3))]:
            f2=tk.Frame(pn,bg=C["panel"]); f2.pack(fill="x",padx=10,pady=2)
            tk.Label(f2,text=lbl+":",font=FNS,width=22,
                     bg=C["panel"],fg=C["texto2"],anchor="w").pack(side="left")
            tk.Label(f2,text=val,font=FN,
                     bg=C["panel"],fg=C["acento"]).pack(side="left",padx=6)
        tk.Label(self.fr_res_rep,
                 text="✓ Listo. Continúa en pestaña Incertidumbre.",
                 font=FNS,bg=C["fondo"],fg=C["ok"]).pack(pady=4)

    # ── TAB 4: GUM ─────────────────────────────────────────
    def _tab_gum(self):
        fr=self._scroll_frame(self.t_gum)
        self._sec(fr,"PARÁMETROS GUM")

        gf=tk.Frame(fr,bg=C["fondo"]); gf.pack(fill="x",padx=20,pady=4)
        self.v_gum_L=tk.StringVar(value="10")
        self.v_gum_dt1=tk.StringVar(value="0,6")
        self.v_gum_dt2=tk.StringVar(value="0,0")
        for i,(lbl,v,nota) in enumerate([
            ("Longitud L (mm)",self.v_gum_L,"punto de mayor error / rango máximo"),
            ("Δt₁ = T_bloque − 20 °C",self.v_gum_dt1,""),
            ("Δt₂ = T_comparador − 20 °C",self.v_gum_dt2,""),
        ]):
            tk.Label(gf,text=lbl+":",font=FNS,bg=C["fondo"],fg=C["texto2"],
                     anchor="w",width=30).grid(row=i,column=0,sticky="w",pady=3)
            tk.Entry(gf,textvariable=v,font=FN,bg=C["entrada"],fg=C["texto"],
                     insertbackground=C["acento"],relief="flat",bd=0,width=14
                     ).grid(row=i,column=1,sticky="w",padx=8,pady=3)
            if nota:
                tk.Label(gf,text=nota,font=FNS,bg=C["fondo"],fg=C["texto2"]
                         ).grid(row=i,column=2,sticky="w",padx=4)

        tk.Button(fr,text="⟶  CALCULAR PRESUPUESTO GUM",
                  command=self._calc_gum,font=FNB,
                  bg=C["acento"],fg=C["enc"],
                  activebackground=C["acento2"],
                  relief="flat",padx=22,pady=10
                  ).pack(pady=12)

        self.fr_gum_tabla=tk.Frame(fr,bg=C["fondo"])
        self.fr_gum_tabla.pack(fill="both",expand=True,padx=20)

    def _calc_gum(self):
        for w in self.fr_gum_tabla.winfo_children(): w.destroy()
        try:
            params={
                "lecs_rep": getattr(self,"_lecs_rep_mm",
                                    [10.004,10.004,10.006,10.006,10.006]),
                "res":      pf(self.v_res.get()) or 0.01,
                "UL_BP":    pf(self.vp["pat_U"].get()) or 0.00011,
                "k_BP":     pf(self.vp["pat_k"].get()) or 2.0,
                "L_mm":     pf(self.v_gum_L.get()) or 10.0,
                "theta":    pf(self.vf["theta"].get()) or 0.5,
                "planitud": pf(self.vp["pat_plan"].get()) or 0.0013,
                "P":        pf(self.vf["P"].get()) or 1.8,
                "D":        pf(self.vf["D"].get()) or 2.5,
                "grado":    self.vp["pat_grado"].get().strip(),
                "dt1":      pf(self.v_gum_dt1.get()) or 0.6,
                "dt2":      pf(self.v_gum_dt2.get()) or 0.0,
                "Ut_cert":  pf(self.vt["Uc"].get()) or 0.02,
                "k_t":      pf(self.vt["kt"].get()) or 2.0,
                "d_t":      pf(self.vt["d"].get()) or 0.01,
                "Ut_der":   pf(self.vt["Ud"].get()) or 0.02,
            }
        except Exception as ex:
            messagebox.showerror("Error",str(ex)); return

        r=GUM(params).calc()
        self.gum_result=r

        fuentes=["Repetibilidad","Bloque patrón + deriva","Error de coseno",
                 "Resolución visualizador","Planitud soporte","Deformación bloque",
                 "Expansión térmica","Variación temperatura"]
        distrib=["Normal","Normal","Rectangular","Rectangular",
                 "Rectangular","Rectangular","Rectangular","Rectangular"]

        self._sec(self.fr_gum_tabla,"PRESUPUESTO DE INCERTIDUMBRE")
        hdr=tk.Frame(self.fr_gum_tabla,bg=C["panel"]); hdr.pack(fill="x")
        for txt,w in [("N°",4),("Fuente",32),("Distrib.",12),
                      ("u std (mm)",16),("% Part.",9)]:
            tk.Label(hdr,text=txt,font=FNS,width=w,
                     bg=C["panel"],fg=C["acento"],pady=5
                     ).pack(side="left")

        for i,(f,d) in enumerate(zip(fuentes,distrib)):
            u=r["u"][i]; p=r["pct"][i]
            bg=C["panel"] if i%2==0 else C["resalt"]
            fil=tk.Frame(self.fr_gum_tabla,bg=bg); fil.pack(fill="x")
            clr_p=C["acento"] if p>=20 else (C["acento2"] if p>=5 else C["texto"])
            for txt,w,clr in [(str(i+1),4,C["texto2"]),(f,32,C["texto"]),
                               (d,12,C["texto2"]),(fm(u,6),16,C["texto"]),
                               (f"{p:.1f}%",9,clr_p)]:
                tk.Label(fil,text=txt,font=FNS,width=w,
                         bg=bg,fg=clr,pady=3).pack(side="left",padx=2)

        # totales
        tot=tk.Frame(self.fr_gum_tabla,bg=C["enc"]); tot.pack(fill="x")
        for lbl,val in [
            ("Incertidumbre combinada  uc",fm(r["uc"],6)+" mm"),
            ("Incertidumbre expandida  U (k=2)",
             fm(r["U_mm"],4)+" mm  =  "+fm(r["U_um"],1)+" µm"),
        ]:
            f2=tk.Frame(tot,bg=C["enc"]); f2.pack(fill="x",padx=10,pady=4)
            tk.Label(f2,text=lbl+":",font=FN,width=40,
                     bg=C["enc"],fg=C["texto2"],anchor="w").pack(side="left")
            tk.Label(f2,text=val,font=("Consolas",12,"bold"),
                     bg=C["enc"],fg=C["acento"]).pack(side="left",padx=8)

        tk.Label(self.fr_gum_tabla,
                 text="✓ Listo. Ve a la pestaña Resultados.",
                 font=FNS,bg=C["fondo"],fg=C["ok"]).pack(pady=6)

    # ── TAB 5: RESULTADOS ──────────────────────────────────
    def _tab_res(self):
        fr=self._scroll_frame(self.t_res)
        self._inner_res=fr

        bf=tk.Frame(fr,bg=C["fondo"]); bf.pack(pady=14)
        tk.Button(bf,text="⟶  GENERAR RESUMEN",
                  command=self._gen_resumen,font=FNB,
                  bg=C["acento2"],fg=C["enc"],
                  activebackground=C["acento"],
                  relief="flat",padx=22,pady=10
                  ).pack(side="left",padx=8)
        tk.Button(bf,text="📄  Emitir PDF",
                  command=self._emitir_pdf,font=FNB,
                  bg=C["acento"],fg=C["enc"],
                  activebackground=C["acento2"],
                  relief="flat",padx=22,pady=10
                  ).pack(side="left",padx=8)
        tk.Button(bf,text="💾  Guardar JSON",
                  command=self._guardar_json,font=FN,
                  bg=C["panel"],fg=C["texto2"],
                  activebackground=C["resalt"],
                  relief="flat",padx=14,pady=10
                  ).pack(side="left",padx=8)

        self.fr_resumen=tk.Frame(fr,bg=C["fondo"])
        self.fr_resumen.pack(fill="both",expand=True,padx=20)

    def _gen_resumen(self):
        for w in self.fr_resumen.winfo_children(): w.destroy()
        if not self.gum_result:
            messagebox.showinfo("Falta","Calcula el presupuesto GUM primero."); return
        emp=pf(self.v_emp.get()) or 0.008
        un=RANGOS[self.rango_var.get()]["un"]
        r=self.gum_result

        self._sec(self.fr_resumen,"DATOS")
        pn=tk.Frame(self.fr_resumen,bg=C["panel"]); pn.pack(fill="x",pady=4)
        for lbl,val in [
            ("Expediente", self.ve["exp"].get()),
            ("Instrumento",f"{self.ve['marca'].get()} {self.ve['modelo'].get()}"),
            ("Rango",       self.rango_var.get()),
            ("Resolución",  self.v_res.get()+" "+self.v_res_un.get()),
            ("Metrólogo",   self.ve["metrologo"].get()),
        ]:
            f2=tk.Frame(pn,bg=C["panel"]); f2.pack(fill="x",padx=10,pady=2)
            tk.Label(f2,text=lbl+":",font=FNS,width=16,
                     bg=C["panel"],fg=C["texto2"],anchor="w").pack(side="left")
            tk.Label(f2,text=val,font=FN,
                     bg=C["panel"],fg=C["texto"]).pack(side="left",padx=6)

        self._sec(self.fr_resumen,"TABLA DE ERRORES")
        hdr=tk.Frame(self.fr_resumen,bg=C["panel"]); hdr.pack(fill="x")
        for txt,w in [(f"Patrón ({un})",14),(f"Indicación ({un})",14),
                      ("Error (mm)",14),(f"EMP±({un})",12),("Conform.",13)]:
            tk.Label(hdr,text=txt,font=FNS,width=w,
                     bg=C["panel"],fg=C["acento"],pady=5
                     ).pack(side="left")

        for i,fila in enumerate(self.filas_err):
            L=pf(fila["patron"].get()); I=pf(fila["indicacion"].get())
            if L is None or I is None: continue
            Corr=pf(fila["corr"].get()) or 0.0
            L_bp=L+Corr/1000
            E=(I-L_bp)*(25.4 if un=="in" else 1.0)
            conf=abs(E)<=emp
            bg=C["panel"] if i%2==0 else C["resalt"]
            fil=tk.Frame(self.fr_resumen,bg=bg); fil.pack(fill="x")
            for txt,w,clr in [
                (fm(L,3),14,C["texto"]),(fm(I,3),14,C["texto"]),
                (fm(E,4),14,C["texto"]),(fm(emp,3),12,C["texto2"]),
                ("✓ CONF." if conf else "✗ NO CONF.",13,
                 C["ok"] if conf else C["error"])]:
                tk.Label(fil,text=txt,font=FNS,width=w,
                         bg=bg,fg=clr,pady=4).pack(side="left",padx=2)

        self._sec(self.fr_resumen,"INCERTIDUMBRE")
        ui=tk.Frame(self.fr_resumen,bg=C["panel"]); ui.pack(fill="x",pady=4)
        tk.Label(ui,
                 text=f"  U(E) = {fm(r['U_mm'],4)} mm  =  {fm(r['U_um'],1)} µm   (k=2, ≈95%)",
                 font=("Consolas",13,"bold"),bg=C["panel"],fg=C["acento"],pady=8
                 ).pack(anchor="w",padx=12)

    # ── IMPORTAR JSON ──────────────────────────────────────
    def _importar_json(self):
        ruta=filedialog.askopenfilename(
            filetypes=[("JSON","*.json"),("Todos","*.*")],
            title="Importar calibración guardada")
        if not ruta: return
        try:
            with open(ruta,"r",encoding="utf-8") as f:
                d=json.load(f)
        except Exception as ex:
            messagebox.showerror("Error",str(ex)); return

        # cargar campos del expediente
        for k,v in self.ve.items():
            if k in d.get("expediente",{}): v.set(d["expediente"][k])
        for k,v in self.vp.items():
            if k in d.get("patron",{}): v.set(d["patron"][k])
        for k,v in self.vf.items():
            if k in d.get("fisico",{}): v.set(d["fisico"][k])
        for k,v in self.vt.items():
            if k in d.get("temperatura",{}): v.set(d["temperatura"][k])
        if "rango" in d: self.rango_var.set(d["rango"]); self._on_rango()
        if "resolucion" in d: self.v_res.set(d["resolucion"])
        if "EMP" in d: self.v_emp.set(d["EMP"])
        if "obs_libre" in d: self.v_obs.set(d["obs_libre"])

        # regenerar tabla de errores y rellenar
        self._gen_tabla_err()
        for i,row in enumerate(d.get("errores_indicacion",[])):
            if i<len(self.filas_err):
                for k,v in self.filas_err[i].items():
                    if k in row: v.set(row[k])

        # GUM
        if "resultado_gum" in d and d["resultado_gum"]:
            self.gum_result=d["resultado_gum"]

        messagebox.showinfo("Importado","Datos cargados correctamente.")

    # ── GUARDAR JSON ───────────────────────────────────────
    def _guardar_json(self):
        datos=self._recopilar_datos()
        ruta=filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON","*.json"),("Todos","*.*")],
            title="Guardar calibración",
            initialfile=f"comp_{self.ve['exp'].get()}_{date.today()}.json")
        if not ruta: return
        with open(ruta,"w",encoding="utf-8") as f:
            json.dump(datos,f,ensure_ascii=False,indent=2)
        messagebox.showinfo("Guardado",f"Datos guardados en:\n{ruta}")

    # ── EMITIR PDF ─────────────────────────────────────────
    def _emitir_pdf(self):
        if not self.gum_result:
            messagebox.showinfo("Falta","Calcula el presupuesto GUM primero."); return
        ruta=filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF","*.pdf"),("Todos","*.*")],
            title="Guardar PDF",
            initialfile=f"CertificadoComparador_{self.ve['exp'].get()}_{date.today()}.pdf")
        if not ruta: return

        datos=self._recopilar_datos()
        ok=generar_pdf(ruta,datos)
        if ok:
            messagebox.showinfo("PDF generado",f"PDF guardado en:\n{ruta}")
            try: os.startfile(ruta)
            except: pass

    def _recopilar_datos(self):
        un=RANGOS[self.rango_var.get()]["un"]
        return {
            "expediente": self.ve["exp"].get(),
            "marca":      self.ve["marca"].get(),
            "modelo":     self.ve["modelo"].get(),
            "serie":      self.ve["serie"].get(),
            "fecha":      self.ve["fecha"].get(),
            "metrologo":  self.ve["metrologo"].get(),
            "supervisor": self.ve["supervisor"].get(),
            "cliente":    self.ve["cliente"].get(),
            "rango":      self.rango_var.get(),
            "resolucion": self.v_res.get()+" "+self.v_res_un.get(),
            "emp":        self.v_emp.get()+" "+self.v_emp_un.get(),
            "emp_val":    self.v_emp.get(),
            "unidad":     un,
            "pat_codigo": self.vp["pat_cod"].get(),
            "pat_cert":   self.vp["pat_cert"].get(),
            "theta":      self.vf["theta"].get(),
            "D_mm":       self.vf["D"].get(),
            "P_N":        self.vf["P"].get(),
            "obs_libre":  self.v_obs.get(),
            "errores":    [{k:v.get() for k,v in f.items()}
                           for f in self.filas_err],
            "repetibilidad":[{k:v.get() for k,v in f.items()}
                              for f in self.filas_rep],
            "gum":        {k:(round(v,8) if isinstance(v,float) else v)
                           for k,v in (self.gum_result or {}).items()},
            # para exportar/importar
            "patron":     {k:v.get() for k,v in self.vp.items()},
            "fisico":     {k:v.get() for k,v in self.vf.items()},
            "temperatura":{k:v.get() for k,v in self.vt.items()},
            "EMP":        self.v_emp.get(),
            "resultado_gum": self.gum_result,
            "fecha_export": datetime.now().isoformat(),
        }

if __name__=="__main__":
    App().mainloop()
