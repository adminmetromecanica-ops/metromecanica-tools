"""
=============================================================
  METROMECANICA — Sistema Multi-Balanza v5.0
  BIOBASE (RS-232) + RADWAG AS (WiFi TCP)
  Procedimiento ABA | ISO/IEC 17025
  + Monitor Ambiental HOBO UX100-011A | OIML R111 M2
  + PDF por ensayo ABA
  + Registro Ambiental Inicio/Fin
  + Informe Mensual HOBO
=============================================================
  pip install pyserial watchdog matplotlib pandas reportlab
=============================================================
"""

import serial
import serial.tools.list_ports
import socket
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv, json, os, re, threading, time
from datetime import datetime, date
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import pandas as pd
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

try:
    from gum_incertidumbre import calcular_incertidumbre_gum, _seccion_gum_pdf
    _GUM_DISPONIBLE = True
except ImportError:
    _GUM_DISPONIBLE = False
    def calcular_incertidumbre_gum(*a, **kw): return None
    def _seccion_gum_pdf(*a, **kw): pass

# ── Síntesis de voz (pyttsx3) ────────────────────────────────────────
# Crear engine nuevo cada vez — evita bug de Windows con runAndWait()

def hablar(texto):
    """Reproduce texto por voz. Crea engine nuevo en cada llamada."""
    def _run():
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 145)
            engine.setProperty('volume', 1.0)
            # Buscar voz en español
            for v in engine.getProperty('voices'):
                if 'spanish' in v.name.lower() or 'es_' in v.id.lower():
                    engine.setProperty('voice', v.id)
                    break
            engine.say(texto)
            engine.runAndWait()
            engine.stop()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

DIR_APP  = os.path.dirname(os.path.abspath(__file__))
FILE_PAT = os.path.join(DIR_APP, "patrones.json")
FILE_CFG = os.path.join(DIR_APP, "config.json")
LOGO_PATH = os.path.join(DIR_APP, "logo_metromecanica.png")

def cargar_config():
    if os.path.exists(FILE_CFG):
        with open(FILE_CFG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "cert_hobo":   "Elicrom 2025",
        "venc_hobo":   "",
        "cert_yowexa": "Pendiente",
        "venc_yowexa": "",
        "presion":     "1014.3",
        "operador":    "",
    }

def guardar_config(cfg):
    with open(FILE_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ════════════════════════════════════════════════════════════
#  CORRECCIONES POR TRAZABILIDAD
# ════════════════════════════════════════════════════════════
FILE_CORR = os.path.join(DIR_APP, "correcciones.json")

# ── Contraseña para editar correcciones por trazabilidad ────────────
# Cambiar por la contraseña deseada
_PASSWORD_CORRECCIONES = "metrolab2024"
_PASSWORD_CARACT       = "caract2024"

def _verificar_password(parent=None):
    """Solicita contraseña antes de acceder a correcciones."""
    import tkinter as tk
    win = tk.Toplevel(parent)
    win.title("Acceso restringido")
    win.geometry("320x160")
    win.configure(bg="#0f1828")
    win.grab_set()
    win.resizable(False, False)
    # Centrar
    win.update_idletasks()

    tk.Frame(win, bg=RED, height=3).pack(fill="x")
    tk.Label(win, text="🔒  Área protegida — Correcciones por Trazabilidad",
             bg="#0f1828", fg=RED,
             font=("Georgia", 8, "bold")).pack(pady=(10,5))
    tk.Label(win, text="Ingresa la contraseña de acceso:",
             bg="#0f1828", fg="#cdd9e5",
             font=("Georgia", 8)).pack()

    var = tk.StringVar()
    e = tk.Entry(win, textvariable=var, show="●", width=22,
                 font=("Courier New", 11),
                 bg="#141f2e", fg="#00c8e0",
                 insertbackground="#00c8e0",
                 relief="flat", bd=3)
    e.pack(pady=8); e.focus_set()

    result = [False]
    def verificar():
        if var.get() == _PASSWORD_CORRECCIONES:
            result[0] = True
            win.destroy()
        else:
            tk.Label(win, text="Contraseña incorrecta",
                     bg="#0f1828", fg=RED,
                     font=("Georgia", 7)).pack()
            var.set("")
            e.focus_set()

    e.bind("<Return>", lambda ev: verificar())
    tk.Button(win, text="Acceder",
              bg=RED, fg="white",
              font=("Georgia", 9, "bold"),
              relief="flat", padx=14, pady=4,
              command=verificar).pack()
    win.wait_window()
    return result[0]

CORR_DEFAULT = {
    # ── Temperatura HOBO — certificado Elicrom ──────────────────
    # X    = Indicacion del termometro HOBO (lectura del instrumento)
    # F(X) = Correccion = VCV - Lectura
    # Fuente: Libro1.xlsx Hoja Temp. Ambiental
    "hobo_temp": [
        {"nominal": 14.99, "lectura": 10.36, "correccion": -0.36},
        {"nominal": 25.01, "lectura": 25.30, "correccion": -0.29},
        {"nominal": 40.16, "lectura": 45.09, "correccion": -0.10},
    ],
    # ── Humedad HOBO — certificado Elicrom ──────────────────────
    # Fuente: Libro1.xlsx Hoja Temp. Ambiental (seccion Humedad)
    "hobo_hr": [
        {"nominal": 30.0, "lectura": 34.5, "correccion": -4.5},
        {"nominal": 60.0, "lectura": 62.9, "correccion": -2.9},
        {"nominal": 90.0, "lectura": 88.9, "correccion":  1.1},
    ],
    # ── Presion Yowexa — actualizar con certificado LFP-011-2024
    "yowexa_presion": [
        {"nominal": 1013.25, "lectura": 1013.25, "correccion": 0.0},
    ],
    "u_temp":   0.21,  # Incertidumbre expandida T (°C), k=2
    "u_hr":     2.5,   # Incertidumbre expandida HR (%), k=2
    "u_presion":1.0,   # Incertidumbre expandida P (mbar), k=2
}

def cargar_correcciones():
    if os.path.exists(FILE_CORR):
        with open(FILE_CORR, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Migrar si HR aun tiene datos en cero (version anterior)
        hr_pts = data.get("hobo_hr", [])
        if not hr_pts or all(abs(p.get("correccion",0)) < 0.001 for p in hr_pts):
            data["hobo_hr"] = CORR_DEFAULT["hobo_hr"]
            guardar_correcciones(data)
        # Migrar si temp tiene nominales incorrectos (10.0, 25.0, 45.0)
        t_pts = data.get("hobo_temp", [])
        if t_pts and abs(t_pts[0].get("nominal",0) - 10.0) < 0.01:
            data["hobo_temp"] = CORR_DEFAULT["hobo_temp"]
            guardar_correcciones(data)
        return data
    return CORR_DEFAULT.copy()

def guardar_correcciones(corr):
    with open(FILE_CORR, "w", encoding="utf-8") as f:
        json.dump(corr, f, indent=2, ensure_ascii=False)

def interpolar_correccion(valor, puntos):
    """
    Interpolación por Polinomio de Lagrange.
    Igual al modelo Excel usado en Metromecanica.

    puntos: lista de {nominal, lectura, correccion}
      lectura    = indicacion del instrumento (X)
      correccion = valor_patron - lectura      (F(X))

    Con 1 punto: correccion constante.
    Con 2 puntos: interpolacion lineal (Lagrange grado 1).
    Con 3+ puntos: polinomio de Lagrange grado n-1.
    Fuera del rango: extrapolacion con el polinomio completo.
    """
    if not puntos:
        return 0.0

    pts = sorted(puntos, key=lambda p: p["lectura"])
    xs  = [p["lectura"]    for p in pts]
    fs  = [p["correccion"] for p in pts]
    n   = len(pts)

    if n == 1:
        return fs[0]

    # Polinomio de Lagrange
    resultado = 0.0
    for i in range(n):
        Li = 1.0
        for j in range(n):
            if i != j:
                denom = xs[i] - xs[j]
                if abs(denom) < 1e-12:
                    continue
                Li *= (valor - xs[j]) / denom
        resultado += fs[i] * Li

    return round(resultado, 6)

def aplicar_correcciones(t_bruta, hr_bruta, p_bruta, corr=None):
    """
    Aplica correcciones por trazabilidad a T, HR y P.
    Retorna dict con valores corregidos e incertidumbres.
    """
    if corr is None:
        corr = cargar_correcciones()
    corr_t = interpolar_correccion(t_bruta,  corr.get("hobo_temp", []))
    corr_h = interpolar_correccion(hr_bruta, corr.get("hobo_hr",   []))
    corr_p = interpolar_correccion(p_bruta,  corr.get("yowexa_presion", []))
    t_corr = round(t_bruta  + corr_t, 4)
    h_corr = round(hr_bruta + corr_h, 4)
    p_corr = round(p_bruta  + corr_p, 4)
    rho_bruta = calcular_densidad_aire(t_bruta,  hr_bruta, p_bruta)
    rho_corr  = calcular_densidad_aire(t_corr,   h_corr,   p_corr)
    return {
        "t_bruta":   t_bruta,  "t_corr":  t_corr,  "corr_t": corr_t,
        "h_bruta":   hr_bruta, "h_corr":  h_corr,  "corr_h": corr_h,
        "p_bruta":   p_bruta,  "p_corr":  p_corr,  "corr_p": corr_p,
        "rho_bruta": rho_bruta,"rho_corr":rho_corr,
        "u_temp":    corr.get("u_temp",   0.21),
        "u_hr":      corr.get("u_hr",     2.5),
        "u_presion": corr.get("u_presion",1.0),
    }

# ── EMP Tabla 1 NMP 004:2007 — Clase M2 (mg) ─────────────────
EMP_M2 = {
    5000000: 800000, 2000000: 300000, 1000000: 160000,
    500000:  80000,  200000:  30000,  100000:  16000,
    50000:   8000,   20000:   3000,   10000:   1600,
    5000:    800,    2000:    300,    1000:    160,
    500:     80,     200:     30,     100:     16,
    50:      10,     20:      8.0,    10:      6.0,
    5:       5.0,    2:       4.0,    1:       3.0,
    0.5:     2.5,    0.2:     2.0,    0.1:     1.6,
    0.05:    1.2,    0.02:    1.0,    0.01:    0.8,
    0.005:   0.6,    0.002:   0.6,    0.001:   0.6,
}

def obtener_emp_m2(nominal_g):
    """Retorna EMP en mg para clase M2 segun NMP 004:2007 Tabla 1."""
    nominal_mg = nominal_g * 1000
    # Buscar el valor nominal exacto o el mas cercano superior
    claves = sorted(EMP_M2.keys())
    for k in claves:
        if nominal_mg <= k * 1000:
            if k in EMP_M2:
                return EMP_M2[k]
    # Busqueda directa
    nom_g = nominal_g
    for k in sorted(EMP_M2.keys(), reverse=True):
        if nom_g >= k:
            return EMP_M2[k]
    return None

def obtener_emp_m2_directo(nominal_g):
    """Retorna EMP en mg buscando coincidencia directa o mas cercana."""
    candidatos = sorted(EMP_M2.keys())
    mejor = None
    for k in candidatos:
        if abs(k - nominal_g) < 0.0001:
            return EMP_M2[k]
    # Si no hay exacto, buscar el inmediatamente superior
    for k in candidatos:
        if k >= nominal_g:
            return EMP_M2[k]
    return list(EMP_M2.values())[-1]

# ── Operadores del laboratorio ───────────────────────────────
FILE_OPS = os.path.join(DIR_APP, "operadores.json")

def cargar_operadores():
    if os.path.exists(FILE_OPS):
        with open(FILE_OPS, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Gabriel Ramirez"]

def guardar_operadores(ops):
    with open(FILE_OPS, "w", encoding="utf-8") as f:
        json.dump(ops, f, indent=2, ensure_ascii=False)

# ── Log de operaciones ───────────────────────────────────────
FILE_LOG = os.path.join(DIR_APP, "log_operaciones.csv")

def registrar_log(evento, operador, detalle=""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existe = os.path.exists(FILE_LOG)
    with open(FILE_LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(["Timestamp","Evento","Operador","Detalle"])
        w.writerow([ts, evento, operador, detalle])

RADWAG_IP   = "192.168.18.65"
RADWAG_PORT = 4001
CARPETA_HOBO = r"D:\\"
CARPETA_MENSUAL = r"D:\\CONDICIONES AMBIENTALES"

def _fmt_rho(rho):
    """Formatea densidad con coma decimal y evalua empuje del aire."""
    if rho is None:
        return "rho: —", "Empuje: —", TXT_DIM, TXT_DIM
    desp, desv = evaluar_empuje_aire(rho)
    rho_txt    = f"rho: {str(rho).replace('.',',')} kg/m3  (CIPM-2007)"
    empuje_txt = (f"Empuje aire: {str(desv).replace('.',',')}%  — DESPRECIABLE"
                  if desp else
                  f"Empuje aire: {str(desv).replace('.',',')}%  — NO DESPRECIABLE")
    return rho_txt, empuje_txt, TEAL, GREEN if desp else RED

# ─── PALETA ──────────────────────────────────────────────────
BG      = "#080d18"; PANEL   = "#0f1828"; PANEL2  = "#141f2e"
BORDER  = "#1a2940"; ACCENT  = "#00c8e0"; ACCENT2 = "#0077b6"
GREEN   = "#22c55e"; RED     = "#ef4444"; YELLOW  = "#f59e0b"
ORANGE  = "#f97316"; TXT     = "#cdd9e5"; TXT_DIM = "#4a6480"
TEAL    = "#0d9488"; PURPLE  = "#7c3aed"
FN_MONO = ("Courier New", 10); FN_UI = ("Georgia", 9)
FN_BIG  = ("Courier New", 26, "bold")
FN_SM   = ("Georgia", 8); FN_TITLE = ("Georgia", 11, "bold")

# ─── LÍMITES OIML R111 M2 ────────────────────────────────────

def _entry_coma(parent, var, **kw):
    """
    Entry que fuerza coma decimal INACAL.
    - Si el usuario tipea punto → se reemplaza por coma automáticamente.
    - Acepta: dígitos, coma, signo más/menos.
    """
    e = tk.Entry(parent, textvariable=var, **kw)

    def _on_key(event):
        # Reemplazar punto por coma en tiempo real
        if event.char == '.':
            pos = e.index(tk.INSERT)
            cur = var.get()
            # Solo insertar coma si no hay ya una coma
            if ',' not in cur:
                var.set(cur[:pos] + ',' + cur[pos:])
                e.icursor(pos + 1)
            return 'break'  # bloquear el punto original

    def _on_focusout(event):
        # Al salir del campo, normalizar: reemplazar cualquier punto restante
        val = var.get().replace('.', ',')
        var.set(val)

    e.bind('<Key>', _on_key)
    e.bind('<FocusOut>', _on_focusout)
    return e
TEMP_MIN    = 18.0; TEMP_MAX    = 27.0
HR_MAX      = 80.0; VAR_MAX_1H  = 3.0; VAR_MAX_12H = 5.0

# ════════════════════════════════════════════════════════════
#  UTILIDADES
# ════════════════════════════════════════════════════════════
def fmt(v, d=4, signo=False):
    """Formatea número con coma decimal (INACAL/Perú)."""
    return format(v, f"{'+' if signo else ''}.{d}f").replace(".", ",")

def fdc(v, d=3, signo=False):
    """Formato con coma decimal — alias corto para uso en PDF."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return format(v, f"{'+' if signo else ''}.{d}f").replace(".", ",")

def parsear_serial(raw):
    m = re.search(r'([+-]?\s*\d+\.?\d*)\s*(g|kg)', raw, re.I)
    if m:
        try:
            v = float(m.group(1).replace(" ", ""))
            return v * 1000 if m.group(2).lower() == "kg" else v
        except: pass
    return None

def parsear_radwag(raw):
    # Protocolo RADWAG AS: "SU A +   0.00000 g" estable, "SD A" inestable
    # Print envía una línea con el valor actual
    estable = "SU A" in raw or "SI A" in raw or "SU" in raw
    # Buscar número con hasta 5 decimales
    m = re.search(r'([+-]?\s*\d+\.?\d*)\s*g', raw, re.I)
    if m:
        try:
            val = float(m.group(1).replace(" ", ""))
            return val, estable
        except: pass
    return None, False

def cargar_patrones():
    if os.path.exists(FILE_PAT):
        with open(FILE_PAT, "r", encoding="utf-8") as f:
            pats = json.load(f)
        # Migración: agregar u_patron y lab_patron si no existen
        changed = False
        for p in pats:
            if "u_patron" not in p:
                p["u_patron"] = 0.060; changed = True
            if "lab_patron" not in p:
                p["lab_patron"] = "—"; changed = True
        if changed:
            with open(FILE_PAT, "w", encoding="utf-8") as f:
                json.dump(pats, f, indent=2, ensure_ascii=False)
        return pats
    anio = str(date.today().replace(year=date.today().year + 1))
    return [
        {"id":"PAT-1kg",   "nominal":1000.0,  "dcr":0.0, "u_patron":0.060, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
        {"id":"PAT-2kg",   "nominal":2000.0,  "dcr":0.0, "u_patron":0.060, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
        {"id":"PAT-5kg",   "nominal":5000.0,  "dcr":0.0, "u_patron":0.060, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
        {"id":"PAT-200mg", "nominal":0.2,     "dcr":0.0, "u_patron":0.010, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
        {"id":"PAT-1g",    "nominal":1.0,     "dcr":0.0, "u_patron":0.010, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
        {"id":"PAT-10g",   "nominal":10.0,    "dcr":0.0, "u_patron":0.020, "n_cert":"—","vencimiento":anio,"lab_patron":"—"},
    ]

def guardar_patrones(p):
    with open(FILE_PAT, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

def estado_vigencia(venc_str):
    try:
        dias = (date.fromisoformat(venc_str) - date.today()).days
        if dias < 0:   return "VENCIDO",    RED,    dias
        if dias <= 30: return "POR VENCER", ORANGE, dias
        if dias <= 90: return "PROXIMO",    YELLOW, dias
        return "VIGENTE", GREEN, dias
    except: return "INVALIDA", RED, 0

def calcular_densidad_aire(T_c, HR_pct, P_mbar):
    """
    Densidad del aire — CIPM-2007.
    Implementacion identica al Excel Libro3.xlsx de Metromecanica.
    Referencia: OIML R111 Anexo B, ecuaciones B.3 a B.8.
    Picard et al., Metrologia 45 (2008) 149-155.

    Entradas:
      T_c    : Temperatura corregida (°C)
      HR_pct : Humedad Relativa corregida (%)
      P_mbar : Presion atmosferica corregida (mbar)

    Retorna: densidad del aire (kg/m3), 6 decimales.
    """
    try:
        import math
        T_K  = T_c + 273.15
        P_Pa = P_mbar * 100.0        # Pa

        # B.6 — Factor de fugacidad f(p,t)  con p en Pa
        f = 1.00062 + 3.14e-8 * P_Pa + 5.6e-7 * T_c**2

        # B.7 — Presion de vapor en saturacion psv(t)  [Pa]
        Psv = math.exp(1.2378847e-5  * T_K**2
                       - 1.9121316e-2 * T_K
                       + 33.93711047
                       - 6.3431645e3  / T_K)

        # B.5 — Fraccion molar de vapor de agua xv
        Xv = (HR_pct / 100.0) * f * Psv / P_Pa

        # B.8 — Factor de compresibilidad Z  con p en Pa
        Z = (1.0
             - (P_Pa / T_K) * (1.58123e-6
                                - 2.9331e-8  * T_c
                                + 1.1043e-10 * T_c**2
                                + (5.707e-6  - 2.051e-8 * T_c) * Xv
                                + (1.9898e-4 - 2.376e-6 * T_c) * Xv**2)
             + (P_Pa**2 / T_K**2) * (1.83e-11 - 0.765e-8 * Xv**2))

        # B.3 — Densidad del aire rho [kg/m3]
        rho = ((P_Pa * 28.96546e-3) / (Z * 8.314472 * T_K)) \
              * (1.0 - Xv * (1.0 - (0.01801528 / 28.96546) * 1e-3))

        return round(rho, 6)
    except:
        return None


def evaluar_empuje_aire(rho, rho_ref=1.2, tol=10.0):
    """
    Evalua si la correccion por empuje del aire es despreciable.
    Segun Excel Libro3: desviacion = |rho_ref - rho| / rho_ref * 100
    Si desviacion < tolerancia (10%) → DESPRECIABLE.
    Retorna: (despreciable: bool, desviacion_pct: float)
    """
    if rho is None:
        return True, 0.0
    desv = abs((rho_ref - rho) / rho_ref) * 100.0
    return desv < tol, round(desv, 4)

def parsear_csv_hobo(filepath):
    try:
        with open(filepath, encoding='latin-1') as f:
            lineas = f.readlines()
        skip = 0
        for i, linea in enumerate(lineas):
            if linea.strip() and linea[0].isdigit():
                skip = i; break
        df = pd.read_csv(filepath, skiprows=skip, header=None, encoding='latin-1')
        df.columns = ['timestamp','temp_c','hr_pct'] + [f'x{i}' for i in range(len(df.columns)-3)]
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='%m/%d/%y %H:%M:%S.%f', errors='coerce')
        df['temp_c'] = pd.to_numeric(df['temp_c'], errors='coerce')
        df['hr_pct'] = pd.to_numeric(df['hr_pct'], errors='coerce')
        return df.dropna(subset=['timestamp','temp_c']).sort_values('timestamp')
    except: return None


# ════════════════════════════════════════════════════════════
#  GENERADORES PDF
# ════════════════════════════════════════════════════════════
def _encabezado_pdf(story, titulo, subtitulo, codigo, version):
    """Encabezado estándar con logo para todos los PDFs."""
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    st_emp  = ParagraphStyle('emp',  fontSize=15, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#8B0000'))
    st_sub2 = ParagraphStyle('sub2', fontSize=8,  fontName='Helvetica-Oblique',
                              textColor=colors.HexColor('#555555'))
    st_cod  = ParagraphStyle('cod',  fontSize=7,  fontName='Helvetica',
                              alignment=TA_RIGHT,
                              textColor=colors.HexColor('#333333'))

    # Logo
    logo_cell = ""
    if os.path.exists(LOGO_PATH):
        logo_cell = Image(LOGO_PATH, width=3.5*cm, height=1.8*cm)

    enc_data = [[
        logo_cell,
        [Paragraph("METROMECANICA", st_emp),
         Paragraph("Laboratorio de Calibración", st_sub2)],
        Paragraph(
            f"Código: {codigo}<br/>Versión: {version}<br/>"
            f"Fecha: {datetime.now().strftime('%d/%m/%Y')}",
            st_cod)
    ]]
    enc = Table(enc_data, colWidths=[4*cm, 9*cm, 4*cm])
    enc.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW', (0,0), (-1,0), 1.2, colors.HexColor('#8B0000')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(enc)
    story.append(Spacer(1, 0.25*cm))

    st_titulo = ParagraphStyle('tit', fontSize=12, fontName='Helvetica-Bold',
                                alignment=TA_CENTER, spaceAfter=2)
    st_subtit = ParagraphStyle('stit', fontSize=9, fontName='Helvetica',
                                alignment=TA_CENTER,
                                textColor=colors.HexColor('#555555'), spaceAfter=4)
    story.append(Paragraph(titulo, st_titulo))
    story.append(Paragraph(subtitulo, st_subtit))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cccccc')))
    story.append(Spacer(1, 0.3*cm))


def generar_pdf_ensayo(ensayo, cond_amb, df_hobo, presion, ruta_salida):
    """PDF completo por ensayo ABA."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable, Image)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import tempfile

    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=1.2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    story = []

    st_sec  = ParagraphStyle('sec', fontSize=9, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#1a3a6b'),
                              spaceBefore=8, spaceAfter=4)
    st_norm = ParagraphStyle('norm', fontSize=8, fontName='Helvetica', spaceAfter=2)
    st_pie  = ParagraphStyle('pie',  fontSize=7, fontName='Helvetica',
                              textColor=colors.grey, alignment=TA_CENTER)
    st_nota = ParagraphStyle('nota', fontSize=7.5, fontName='Helvetica-Oblique',
                              textColor=colors.HexColor('#555555'))

    _encabezado_pdf(story, "HOJA DE TRABAJO — ENSAYO ABA",
                    f"Calibración de Pesas Clase M2 | OIML R111 | ISO/IEC 17025 | "
                    f"N° {ensayo.get('n','—')}",
                    "HTA-001", "1.0")

    # ── 1. Datos generales ───────────────────────────────────
    story.append(Paragraph("1. DATOS GENERALES", st_sec))
    gen_data = [
        ["OT / Referencia:", ensayo.get('ot','—'),
         "Fecha / Hora:", ensayo.get('timestamp','—')],
        ["Operador:", ensayo.get('operador','—'),
         "Balanza:", ensayo.get('balanza','—')],
        ["N° Ensayo:", str(ensayo.get('n','—')),
         "ID Pesa:", ensayo.get('id_pesa','—')],
        ["RUC cliente:", ensayo.get('ruc','—'),
         "Razón social:", ensayo.get('razon_social','—')],
        ["Dirección fiscal:", ensayo.get('direccion','—'), "", ""],
    ]
    gen_t = Table(gen_data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 4.5*cm])
    gen_t.setStyle(_estilo_tabla_datos())
    story.append(gen_t)
    story.append(Spacer(1, 0.2*cm))

    # ── 2. Datos del patrón ──────────────────────────────────
    story.append(Paragraph("2. DATOS DEL PATRÓN", st_sec))
    pat_data = [
        ["ID Patrón:", ensayo.get('patron_id','—'),
         "Nominal (g):", fmt(ensayo.get('nominal',0), 4)],
        ["N° Certificado:", ensayo.get('n_cert','—'),
         "delta_mcr (g):", fmt(ensayo.get('dcr',0), 4, True)],
        ["Entidad calibrante:", ensayo.get('lab_patron','—'),
         "Vencimiento cert.:", ensayo.get('venc_patron','—')],
        ["U expandida patrón (k=2):",
         fmt(ensayo.get('u_patron',0.060), 4) + " g  →  " +
         fmt(ensayo.get('u_patron',0.060)*1000, 1) + " mg",
         "u_R = U/2 =",
         fmt(ensayo.get('u_patron',0.060)/2*1000, 1) + " mg"],
    ]
    pat_t = Table(pat_data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 4.5*cm])
    pat_t.setStyle(_estilo_tabla_datos())
    story.append(pat_t)
    story.append(Spacer(1, 0.2*cm))

    # ── 3. Resultados ABA ────────────────────────────────────
    story.append(Paragraph("3. RESULTADOS PROCEDIMIENTO ABA", st_sec))
    story.append(Paragraph(
        "Formula: delta_mct = It - (Ir1 + Ir2) / 2 + delta_mcr", st_nota))
    story.append(Spacer(1, 0.15*cm))

    d = ensayo.get('decimales', 4)
    ir1     = ensayo.get('ir1', 0)
    it      = ensayo.get('it', 0)
    ir2     = ensayo.get('ir2', 0)
    ir_prom = ensayo.get('ir_prom', 0)
    dct     = ensayo.get('dct', 0)

    ok_color  = colors.HexColor('#d4edda')
    nok_color = colors.HexColor('#f8d7da')
    res_color = ok_color if abs(dct) < 1.0 else nok_color

    # EMP — calcular siempre desde nominal para garantizar valor correcto
    nominal_g = ensayo.get('nominal', 0)
    emp_mg    = ensayo.get('emp_mg', None)
    if not emp_mg and nominal_g:
        emp_mg = obtener_emp_m2_directo(nominal_g)
    dct_mg   = ensayo.get('dct_mg', abs(dct)*1000)
    if not dct_mg:
        dct_mg = abs(dct) * 1000
    conforme = ensayo.get('conforme_emp', None)
    if conforme is None and emp_mg:
        conforme = dct_mg <= emp_mg
    elif conforme is None:
        conforme = True
    emp_txt   = fdc(emp_mg, 3) if emp_mg else "—"
    dct_mg_txt= fdc(dct_mg, 3, signo=True)
    conf_txt  = "CONFORME" if conforme else "NO CONFORME"

    res_data = [
        ["Parámetro", "Valor (g)", "Descripción"],
        ["Ir1",       fmt(ir1, d),  "1ra lectura patron"],
        ["It",        fmt(it,  d),  "Lectura incognita"],
        ["Ir2",       fmt(ir2, d),  "2da lectura patron"],
        ["Ir_prom",   fmt(ir_prom,d), "(Ir1 + Ir2) / 2"],
        ["delta_mct", fmt(dct,d,True),
         f"Diferencia de masa convencional = {dct_mg_txt}"],
        ["EMP clase M2",
         fdc(emp_mg, 3) + " mg" if emp_mg else "—",
         f"Error Max. Permisible NMP 004:2007 Tabla 1  ({fdc(emp_mg/1000,3) if emp_mg else '—'} g)"],
        ["Conformidad M2", conf_txt,
         f"delta_mct = {dct_mg_txt} mg  |  EMP = {fdc(emp_mg,3)+' mg' if emp_mg else '—'}  |  NMP 004:2007"],
    ]
    res_t = Table(res_data, colWidths=[4*cm, 4*cm, 9*cm])
    res_style = TableStyle([
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 8),
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',     (0,0), (-1,0),  colors.white),
        ('ALIGN',         (1,0), (1,-1),  'CENTER'),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ])
    # Colores alternos filas 1-4
    for i in range(1, 5):
        res_style.add('BACKGROUND', (0,i), (-1,i),
                      colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5'))
    # Fila delta_mct
    res_style.add('BACKGROUND', (0,5), (-1,5), res_color)
    res_style.add('FONTNAME',   (0,5), (-1,5), 'Helvetica-Bold')
    # Fila EMP — amarillo
    res_style.add('BACKGROUND', (0,6), (-1,6), colors.HexColor('#fff3cd'))
    res_style.add('FONTNAME',   (0,6), (-1,6), 'Helvetica-Bold')
    res_style.add('FONTSIZE',   (0,6), (-1,6), 8.5)
    # Fila conformidad — verde o rojo
    conf_color = ok_color if conforme else nok_color
    res_style.add('BACKGROUND', (0,7), (-1,7), conf_color)
    res_style.add('FONTNAME',   (0,7), (-1,7), 'Helvetica-Bold')
    res_style.add('FONTSIZE',   (0,7), (-1,7), 9)
    res_style.add('FONTCOLOR',  (1,7), (1,7),
                  colors.HexColor('#155724') if conforme else colors.HexColor('#c0392b'))
    res_style.add('LINEABOVE',  (0,6), (-1,6), 1.0, colors.HexColor('#999999'))
    res_t.setStyle(res_style)
    story.append(res_t)
    story.append(Spacer(1, 0.2*cm))

    # ── 4. Condiciones ambientales inicio/fin ────────────────
    story.append(Paragraph("4. CONDICIONES AMBIENTALES", st_sec))
    ci = cond_amb.get('inicio', {})
    cf = cond_amb.get('fin',    {})

    # Usar valores CORREGIDOS si existen, sino brutos
    def get_corr_val(cond, key_corr, key_bruto):
        c = cond.get('corr', {}) if cond else {}
        return c.get(key_corr, cond.get(key_bruto)) if c else cond.get(key_bruto) if cond else None

    t_i  = get_corr_val(ci, 't_corr', 'temp')
    t_f  = get_corr_val(cf, 't_corr', 'temp')
    h_i  = get_corr_val(ci, 'h_corr', 'hr')
    h_f  = get_corr_val(cf, 'h_corr', 'hr')
    p_i  = get_corr_val(ci, 'p_corr', 'presion') or presion
    p_f  = get_corr_val(cf, 'p_corr', 'presion') or presion

    rho_i = calcular_densidad_aire(t_i, h_i, p_i) if (t_i is not None and h_i is not None) else None
    rho_f = calcular_densidad_aire(t_f, h_f, p_f) if (t_f is not None and h_f is not None) else None

    def fval(v, dec=4):
        if v is None: return '—'
        return f"{v:.{dec}f}".replace('.', ',')

    amb_data = [
        ["Parámetro", "INICIO", "FIN", "Límite OIML R111 M2", "Conforme"],
        ["Temperatura (°C)",
         fval(t_i, 4), fval(t_f, 4),
         f"{str(TEMP_MIN).replace('.',',')} – {str(TEMP_MAX).replace('.',',')} °C",
         _check(t_i, t_f, TEMP_MIN, TEMP_MAX)],
        ["Humedad Relativa (%)",
         fval(h_i, 2), fval(h_f, 2),
         f"< {str(HR_MAX).replace('.',',')}% (no condensación)",
         _check_max(h_i, h_f, HR_MAX)],
        ["Presión atm. (mbar)",
         fval(p_i, 2), fval(p_f, 2),
         "CIPM-2007 (empuje del aire)", "✓"],
        ["Densidad aire (kg/m3)",
         fval(rho_i, 6), fval(rho_f, 6),
         "ref. 1,1839 kg/m3", "✓"],
        ["Hora registro",
         ci.get('hora', '—') if ci else '—',
         cf.get('hora', '—') if cf else '—',
         "—", "—"],
    ]
    amb_t = Table(amb_data, colWidths=[4*cm, 2.5*cm, 2.5*cm, 5*cm, 2*cm])
    amb_s = TableStyle([
        ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
        ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
        ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ])
    for i in range(1, len(amb_data)):
        c = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
        amb_s.add('BACKGROUND', (0,i), (-1,i), c)
        # Colorear columna conforme
        if amb_data[i][4] == '✓':
            amb_s.add('BACKGROUND', (4,i), (4,i), ok_color)
        elif amb_data[i][4] == '✗':
            amb_s.add('BACKGROUND', (4,i), (4,i), nok_color)
    amb_t.setStyle(amb_s)
    story.append(amb_t)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        f"Equipo T/HR: HOBO UX100-011A  S/N: 21065652  |  "
        f"Equipo presión: Yowexa YEM-70AL  S/N: 23111620018  |  "
        f"Presión ingresada manualmente.", st_nota))
    story.append(Spacer(1, 0.2*cm))

    # ── 5. Estado OIML R111 M2 + Densidad del aire ───────────
    story.append(Paragraph("5. ESTADO OIML R111 M2 Y DENSIDAD DEL AIRE", st_sec))

    # Calcular variación ini→fin con valores corregidos
    def _vc(cond, key_c, key_b):
        c = cond.get('corr', {}) if cond else {}
        return c.get(key_c, cond.get(key_b)) if c else (cond.get(key_b) if cond else None)

    t_ini = _vc(ci, 't_corr', 'temp')
    t_fin = _vc(cf, 't_corr', 'temp')
    h_ini = _vc(ci, 'h_corr', 'hr')
    h_fin = _vc(cf, 'h_corr', 'hr')

    var_t = abs(t_fin - t_ini) if (t_ini is not None and t_fin is not None) else None

    def ok_sym(val, lim_min=None, lim_max=None, lim_var=None):
        if val is None: return '—'
        if lim_var is not None:
            return '✓' if val <= lim_var else '✗'
        if lim_min is not None and lim_max is not None:
            return '✓' if lim_min <= val <= lim_max else '✗'
        return '—'

    def fv4(v):
        if v is None: return '—'
        return f"{v:.4f}".replace('.', ',')

    # Calcular densidad promedio ini+fin
    rho_ini = rho_i
    rho_fin = rho_f
    rho_prom = None
    if rho_ini and rho_fin:
        rho_prom = round((rho_ini + rho_fin) / 2, 6)
    elif rho_ini:
        rho_prom = rho_ini

    desp, desv = evaluar_empuje_aire(rho_prom) if rho_prom else (True, 0.0)

    ok_c  = colors.HexColor('#d4edda')
    nok_c = colors.HexColor('#f8d7da')
    ref_c = colors.HexColor('#fff3cd')

    oiml_rows = [
        ["Parámetro", "INICIO (corr)", "FIN (corr)", "Límite OIML R111 M2", "Estado"],
        ["Temperatura (°C)",
         fv4(t_ini), fv4(t_fin),
         f"{str(TEMP_MIN).replace('.',',')} – {str(TEMP_MAX).replace('.',',')} °C",
         ok_sym(t_ini, TEMP_MIN, TEMP_MAX) if t_ini and ok_sym(t_fin, TEMP_MIN, TEMP_MAX) == '✓' else (ok_sym(t_ini, TEMP_MIN, TEMP_MAX))],
        ["Humedad Relativa (%)",
         fv4(h_ini) if h_ini else '—', fv4(h_fin) if h_fin else '—',
         f"< {str(HR_MAX).replace('.',',')}% (no condensación)",
         '✓' if (h_ini and h_fin and h_ini <= HR_MAX and h_fin <= HR_MAX) else '✗'],
        ["Variación T ini→fin (°C)",
         "—", fv4(var_t) if var_t is not None else '—',
         f"≤ ±{str(VAR_MAX_1H).replace('.',',')} °C/h",
         ok_sym(var_t, lim_var=VAR_MAX_1H)],
        ["Densidad aire — INICIO (kg/m3)",
         str(rho_ini).replace('.', ',') if rho_ini else '—', "—",
         "CIPM-2007", "✓"],
        ["Densidad aire — FIN (kg/m3)",
         "—", str(rho_fin).replace('.', ',') if rho_fin else '—',
         "CIPM-2007", "✓"],
        ["Densidad aire — PROMEDIO (kg/m3)",
         str(rho_prom).replace('.', ',') if rho_prom else '—', "—",
         "ref. 1,1839 kg/m3", "✓"],
        ["Corrección por empuje del aire",
         f"{str(desv).replace('.', ',')}%", "—",
         "Tolerancia ±10%",
         "DESPRECIABLE" if desp else "NO DESPRECIABLE"],
    ]

    oiml_t = Table(oiml_rows, colWidths=[5*cm, 3*cm, 3*cm, 4.5*cm, 2.5*cm])
    oiml_s = TableStyle([
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 7.5),
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTNAME',      (0,1), (0,-1),  'Helvetica-Bold'),
        ('GRID',          (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ])
    # Colores alternos y estado
    for i, row in enumerate(oiml_rows[1:], start=1):
        bg = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
        oiml_s.add('BACKGROUND', (0,i), (-1,i), bg)
        estado = row[4]
        if estado == '✓' or estado == 'DESPRECIABLE':
            oiml_s.add('BACKGROUND', (4,i), (4,i), ok_c)
            oiml_s.add('FONTNAME',   (4,i), (4,i), 'Helvetica-Bold')
        elif estado == '✗' or estado == 'NO DESPRECIABLE':
            oiml_s.add('BACKGROUND', (4,i), (4,i), nok_c)
            oiml_s.add('FONTNAME',   (4,i), (4,i), 'Helvetica-Bold')
        elif estado == '—':
            oiml_s.add('BACKGROUND', (4,i), (4,i), ref_c)

    oiml_t.setStyle(oiml_s)
    story.append(oiml_t)
    story.append(Spacer(1, 0.2*cm))

    # ── 6. PRESUPUESTO GUM ──────────────────────────────────
    if _GUM_DISPONIBLE:
        _d_bal = 1 if 'WANT' in ensayo.get('balanza','') else (
                 5 if 'RADWAG' in ensayo.get('balanza','') else 2)
        gum_resultado = calcular_incertidumbre_gum(
            ensayo=ensayo, rho_prom=rho_prom, n_series=1,
            s_series=0.300,
            u_patron_expandida=float(ensayo.get('u_patron', 0.060)),
            d_resolucion=float(_d_bal), nu_patron=float('inf'),
            rho_pesa=8000.0, rho_patron=8000.0,
            nominal_g=ensayo.get('nominal', 20000.0),
        )
        if gum_resultado:
            _seccion_gum_pdf(story, gum_resultado, st_sec, st_nota, colors, cm)
    else:
        story.append(Paragraph("6. PRESUPUESTO DE INCERTIDUMBRE — GUM", st_sec))
        story.append(Paragraph("Módulo gum_incertidumbre.py no encontrado.", st_nota))
        story.append(Spacer(1, 0.2*cm))

    # ── 7. Gráfica HOBO ─────────────────────────────────────
    if df_hobo is not None and len(df_hobo) > 0:
        story.append(Paragraph("6. GRÁFICA CONDICIONES AMBIENTALES (HOBO)", st_sec))
        tmp_img = tempfile.mktemp(suffix='.png')
        _grafica_hobo_pdf(df_hobo, tmp_img)
        if os.path.exists(tmp_img):
            story.append(Image(tmp_img, width=17*cm, height=6*cm))
            story.append(Spacer(1, 0.1*cm))
        n_sec = 8
    else:
        n_sec = 8

    # ── 6. Trazabilidad equipos ──────────────────────────────
    story.append(Paragraph(f"{n_sec}. TRAZABILIDAD DE EQUIPOS DE MEDICIÓN", st_sec))
    traz_data = [
        ["Equipo", "Modelo", "S/N", "Certif.", "Lab. calibrante", "Vencimiento"],
        ["Termohigrómetro", "HOBO UX100-011A", "21065652",
         cond_amb.get('cert_hobo','—'), "Elicrom", cond_amb.get('venc_hobo','—')],
        ["Barómetro", "Yowexa YEM-70AL", "23111620018",
         cond_amb.get('cert_yowexa','Pendiente'), "—", cond_amb.get('venc_yowexa','—')],
    ]
    traz_t = Table(traz_data, colWidths=[3.5*cm, 3.5*cm, 2.5*cm, 2*cm, 2.5*cm, 3*cm])
    traz_t.setStyle(TableStyle([
        ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 7.5),
        ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
        ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('BACKGROUND', (0,1), (-1,1),  colors.white),
        ('BACKGROUND', (0,2), (-1,2),  colors.HexColor('#f5f5f5')),
    ]))
    story.append(traz_t)
    story.append(Spacer(1, 0.3*cm))

    # ── 7. Firmas ────────────────────────────────────────────
    story.append(Paragraph(f"{n_sec+1}. FIRMAS", st_sec))
    firmas_data = [
        ["Ejecutado por:", "", "Revisado por:", ""],
        ["", "", "", ""],
        ["", "", "", ""],
        [f"Operador: {ensayo.get('operador','_'*25)}",
         f"Fecha: {datetime.now().strftime('%d/%m/%Y')}",
         "Resp. técnico: _________________",
         "Fecha: ___________"],
    ]
    firmas_t = Table(firmas_data, colWidths=[5*cm, 3.5*cm, 5.5*cm, 3*cm])
    firmas_t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,0), (0,0), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,0), 'Helvetica-Bold'),
        ('LINEABOVE', (0,2), (1,2), 0.5, colors.black),
        ('LINEABOVE', (2,2), (3,2), 0.5, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(firmas_t)

    # ── Pie ──────────────────────────────────────────────────
    story.append(Spacer(1, 0.3*cm))
    from reportlab.platypus import HRFlowable
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph(
        f"METROMECANICA — Laboratorio de Calibración  |  Lima, Perú  |  "
        f"HTA-001 v1.0  |  Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  |  "
        f"Sistema Multi-Balanza v5.0",
        st_pie))

    doc.build(story)
    return True


def generar_informe_mensual(df_hobo, mes_str, operador, presion, ruta_salida):
    """PDF informe mensual del HOBO para auditor."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable, Image)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import tempfile
    import numpy as np

    doc = SimpleDocTemplate(ruta_salida, pagesize=A4,
                            topMargin=1.2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    story = []

    st_sec  = ParagraphStyle('sec', fontSize=9, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#1a3a6b'),
                              spaceBefore=8, spaceAfter=4)
    st_pie  = ParagraphStyle('pie', fontSize=7, fontName='Helvetica',
                              textColor=colors.grey, alignment=TA_CENTER)
    st_nota = ParagraphStyle('nota', fontSize=7.5, fontName='Helvetica-Oblique',
                              textColor=colors.HexColor('#555555'))

    _encabezado_pdf(story,
                    f"INFORME MENSUAL DE CONDICIONES AMBIENTALES",
                    f"Período: {mes_str}  |  HOBO UX100-011A  S/N: 21065652  |  OIML R111 M2",
                    "IMA-001", "1.0")

    # ── Estadísticas ─────────────────────────────────────────
    story.append(Paragraph("1. ESTADÍSTICAS DEL PERÍODO", st_sec))

    temp = df_hobo['temp_c'].dropna()
    hr   = df_hobo['hr_pct'].dropna()
    n    = len(df_hobo)

    # % tiempo dentro de rango
    t_ok_pct  = (((temp >= TEMP_MIN) & (temp <= TEMP_MAX)).sum() / len(temp) * 100) if len(temp) > 0 else 0
    hr_ok_pct = ((hr <= HR_MAX).sum() / len(hr) * 100) if len(hr) > 0 else 0

    ok_c  = colors.HexColor('#d4edda')
    nok_c = colors.HexColor('#f8d7da')

    est_data = [
        ["Parámetro", "Mín", "Máx", "Media", "Desv. Est.", "% Dentro rango", "Límite"],
        ["Temperatura (°C)",
         fdc(temp.min(), 2), fdc(temp.max(), 2),
         fdc(temp.mean(), 2), fdc(temp.std(), 2),
         fdc(t_ok_pct, 1) + '%', f"{str(TEMP_MIN).replace(chr(46),chr(44))}–{str(TEMP_MAX).replace(chr(46),chr(44))} °C"],
        ["Humedad Relativa (%)",
         fdc(hr.min(), 1), fdc(hr.max(), 1),
         fdc(hr.mean(), 1), fdc(hr.std(), 1),
         fdc(hr_ok_pct, 1) + '%', f"< {HR_MAX}%"],
    ]
    est_t = Table(est_data, colWidths=[3.5*cm,1.8*cm,1.8*cm,1.8*cm,1.8*cm,2.8*cm,3.5*cm])
    est_s = TableStyle([
        ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
        ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
        ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
        ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,1), (-1,1),
         ok_c if t_ok_pct >= 95 else nok_c),
        ('BACKGROUND', (0,2), (-1,2),
         ok_c if hr_ok_pct >= 95 else nok_c),
    ])
    est_t.setStyle(est_s)
    story.append(est_t)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        f"Total de registros del período: {n}  |  "
        f"Equipo: HOBO UX100-011A  S/N: 21065652  |  "
        f"Presión referencia: {presion} mbar (Yowexa YEM-70AL)",
        st_nota))
    story.append(Spacer(1, 0.2*cm))

    # ── Gráfica completa ─────────────────────────────────────
    story.append(Paragraph("2. COMPORTAMIENTO MENSUAL", st_sec))
    tmp_img = tempfile.mktemp(suffix='.png')
    _grafica_hobo_mensual(df_hobo, tmp_img, mes_str)
    if os.path.exists(tmp_img):
        story.append(Image(tmp_img, width=17*cm, height=9*cm))
    story.append(Spacer(1, 0.2*cm))

    # ── Incidencias ──────────────────────────────────────────
    story.append(Paragraph("3. REGISTRO DE INCIDENCIAS", st_sec))

    incidencias = []
    for _, row in df_hobo.iterrows():
        if row['temp_c'] < TEMP_MIN or row['temp_c'] > TEMP_MAX:
            incidencias.append([
                str(row['timestamp'])[:16],
                "Temperatura fuera de rango",
                f"{row['temp_c']:.2f} °C".replace('.',','),
                f"{str(TEMP_MIN).replace(chr(46),chr(44))}–{str(TEMP_MAX).replace(chr(46),chr(44))} °C"
            ])
        if pd.notna(row['hr_pct']) and row['hr_pct'] > HR_MAX:
            incidencias.append([
                str(row['timestamp'])[:16],
                "HR fuera de rango",
                f"{row['hr_pct']:.1f} %".replace('.',','),
                f"< {HR_MAX} %"
            ])

    if incidencias:
        inc_data = [["Timestamp", "Tipo de incidencia", "Valor", "Límite"]] + incidencias[:30]
        inc_t = Table(inc_data, colWidths=[4*cm, 6*cm, 3.5*cm, 3.5*cm])
        inc_t.setStyle(TableStyle([
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 7.5),
            ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
            ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('ROWBACKGROUNDS', (0,1), (-1,-1),
             [colors.white, colors.HexColor('#fff3cd')]),
        ]))
        story.append(inc_t)
        if len(incidencias) > 30:
            story.append(Paragraph(
                f"* Se muestran las primeras 30 de {len(incidencias)} incidencias totales.",
                st_nota))
    else:
        inc_data = [["Sin incidencias en el período — Todas las condiciones dentro de límites OIML R111 M2"]]
        inc_t = Table(inc_data, colWidths=[17*cm])
        inc_t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), ok_c),
            ('FONTNAME',   (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(inc_t)

    story.append(Spacer(1, 0.3*cm))

    # ── Conclusión ───────────────────────────────────────────
    story.append(Paragraph("4. CONCLUSIÓN", st_sec))
    todas_ok = t_ok_pct >= 95 and hr_ok_pct >= 95
    concl_txt = (
        "Las condiciones ambientales del laboratorio se mantuvieron dentro de los "
        "límites OIML R111 para clase M2 durante al menos el 95% del período evaluado. "
        "Las calibraciones realizadas en este período son válidas."
        if todas_ok else
        "Se detectaron condiciones fuera de rango durante el período. "
        "Revisar las incidencias registradas y evaluar impacto en calibraciones realizadas."
    )
    concl_data = [[Paragraph(
        f"<b>{'CONFORME' if todas_ok else 'REVISION REQUERIDA'}:</b> {concl_txt}",
        ParagraphStyle('c', fontSize=8, fontName='Helvetica',
                       textColor=colors.HexColor('#155724') if todas_ok
                       else colors.HexColor('#721c24')))]]
    concl_t = Table(concl_data, colWidths=[17*cm])
    concl_t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1),
         ok_c if todas_ok else nok_c),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('BOX', (0,0), (-1,-1), 0.5,
         colors.HexColor('#155724') if todas_ok else colors.HexColor('#721c24')),
    ]))
    story.append(concl_t)
    story.append(Spacer(1, 0.4*cm))

    # ── Firmas ───────────────────────────────────────────────
    story.append(Paragraph("5. FIRMAS Y APROBACIÓN", st_sec))
    firmas_data = [
        ["Elaborado por:", "", "Aprobado por:", ""],
        ["", "", "", ""],
        ["", "", "", ""],
        [f"Responsable ambiental: {operador}",
         f"Fecha: {datetime.now().strftime('%d/%m/%Y')}",
         "Director técnico: _________________",
         "Fecha: ___________"],
    ]
    firmas_t = Table(firmas_data, colWidths=[5.5*cm, 3*cm, 5.5*cm, 3*cm])
    firmas_t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,0), (0,0), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,0), 'Helvetica-Bold'),
        ('LINEABOVE', (0,2), (1,2), 0.5, colors.black),
        ('LINEABOVE', (2,2), (3,2), 0.5, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(firmas_t)

    # ── Pie ──────────────────────────────────────────────────
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph(
        f"METROMECANICA — Laboratorio de Calibración  |  Lima, Perú  |  "
        f"IMA-001 v1.0  |  Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        st_pie))

    doc.build(story)
    return True


def _estilo_tabla_datos():
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    return TableStyle([
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME',   (2,0), (2,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f0f4ff')),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#f0f4ff')),
        ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0,0), (-1,-1),
         [colors.white, colors.HexColor('#fafafa')]),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ])

def _check(v_ini, v_fin, vmin, vmax):
    if v_ini is None or v_fin is None: return '—'
    return '✓' if (vmin <= v_ini <= vmax and vmin <= v_fin <= vmax) else '✗'

def _check_max(v_ini, v_fin, vmax):
    if v_ini is None or v_fin is None: return '—'
    return '✓' if (v_ini <= vmax and v_fin <= vmax) else '✗'

def _grafica_hobo_pdf(df, ruta_img):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 4),
                                   facecolor='white', sharex=True)
    fig.subplots_adjust(hspace=0.35, left=0.07, right=0.94,
                        top=0.88, bottom=0.18)
    # Temperatura
    ax1.axhspan(TEMP_MIN, TEMP_MAX, alpha=0.12, color='green')
    ax1.axhline(TEMP_MIN, color='red', lw=1, ls='--', alpha=0.6)
    ax1.axhline(TEMP_MAX, color='red', lw=1, ls='--', alpha=0.6)
    ax1.plot(df['timestamp'], df['temp_c'], color='#c0392b', lw=1.2)
    ax1.set_ylabel('T (°C)', fontsize=7, color='#c0392b')
    ax1.tick_params(labelsize=6, colors='#333333')
    ax1.set_title('Temperatura — HOBO UX100-011A', fontsize=8, pad=3)
    ax1.grid(True, alpha=0.3)
    ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False)
    # HR
    ax2.axhspan(0, HR_MAX, alpha=0.08, color='blue')
    ax2.axhline(HR_MAX, color='navy', lw=1, ls='--', alpha=0.6)
    ax2.plot(df['timestamp'], df['hr_pct'], color='#2980b9', lw=1.2)
    ax2.set_ylabel('HR (%)', fontsize=7, color='#2980b9')
    ax2.tick_params(labelsize=6, colors='#333333')
    ax2.set_title('Humedad Relativa', fontsize=8, pad=3)
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    ax2.spines['top'].set_visible(False); ax2.spines['right'].set_visible(False)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m\n%H:%M'))
    fig.autofmt_xdate(rotation=20, ha='right')
    plt.savefig(ruta_img, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)

def _grafica_hobo_mensual(df, ruta_img, mes_str):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 6),
                                   facecolor='white', sharex=True)
    fig.subplots_adjust(hspace=0.4, left=0.06, right=0.97,
                        top=0.90, bottom=0.12)
    fig.suptitle(f'Comportamiento Ambiental Mensual — {mes_str}',
                 fontsize=10, fontweight='bold')
    # Temperatura
    ax1.axhspan(TEMP_MIN, TEMP_MAX, alpha=0.12, color='green', label='Rango válido')
    ax1.axhline(TEMP_MIN, color='red', lw=1, ls='--', alpha=0.7, label=f'Mín {TEMP_MIN}°C')
    ax1.axhline(TEMP_MAX, color='red', lw=1, ls='--', alpha=0.7, label=f'Máx {TEMP_MAX}°C')
    ax1.plot(df['timestamp'], df['temp_c'], color='#c0392b', lw=0.8, alpha=0.9)
    ax1.set_ylabel('Temperatura (°C)', fontsize=8)
    ax1.tick_params(labelsize=7)
    ax1.legend(fontsize=6, loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False)
    # HR
    ax2.axhspan(0, HR_MAX, alpha=0.08, color='blue', label='Zona válida')
    ax2.axhline(HR_MAX, color='navy', lw=1, ls='--', alpha=0.7, label=f'Máx {HR_MAX}%')
    ax2.plot(df['timestamp'], df['hr_pct'], color='#2980b9', lw=0.8, alpha=0.9)
    ax2.set_ylabel('Humedad Relativa (%)', fontsize=8)
    ax2.set_ylim(0, 100)
    ax2.tick_params(labelsize=7)
    ax2.legend(fontsize=6, loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.spines['top'].set_visible(False); ax2.spines['right'].set_visible(False)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
    fig.autofmt_xdate(rotation=20, ha='right')
    plt.savefig(ruta_img, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)


# ════════════════════════════════════════════════════════════
#  PANEL AMBIENTAL
# ════════════════════════════════════════════════════════════
class PanelAmbiente(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.df_hobo     = None
        self.observer    = None
        self.vigilando   = False
        self.ot_var          = tk.StringVar(value="")
        self.instrumento_var = tk.StringVar(value="")
        cfg = cargar_config()
        self.cert_hobo_var   = tk.StringVar(value=cfg.get("cert_hobo",   "Elicrom 2025"))
        self.venc_hobo_var   = tk.StringVar(value=cfg.get("venc_hobo",   ""))
        self.cert_yowexa_var = tk.StringVar(value=cfg.get("cert_yowexa", "Pendiente"))
        self.venc_yowexa_var = tk.StringVar(value=cfg.get("venc_yowexa", ""))
        self.presion_var     = tk.StringVar(value=cfg.get("presion",     "1014.3"))
        self.operador_var    = tk.StringVar(value=cfg.get("operador",    ""))
        self.cond_inicio = {}
        self.cond_fin    = {}
        # Historial de registros manuales para gráfica acumulativa
        self.registros_manuales = []
        # Correcciones por trazabilidad
        self.correcciones = cargar_correcciones()
        self._build()

    def _build(self):
        tk.Frame(self, bg=PURPLE, height=3).pack(fill="x")
        hdr = tk.Frame(self, bg=PANEL2, padx=16, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="MONITOR AMBIENTAL",
                 bg=PANEL2, fg=PURPLE,
                 font=("Georgia", 11, "bold")).pack(side="left")
        tk.Label(hdr, text="  HOBO UX100-011A  S/N:21065652  |  OIML R111 Clase M2",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(side="left")
        self.lbl_banner = tk.Label(hdr, text="● Sin datos",
                                   bg=PANEL2, fg=TXT_DIM,
                                   font=("Courier New", 9, "bold"))
        self.lbl_banner.pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        col_izq = tk.Frame(body, bg=BG, width=380)
        col_izq.pack(side="left", fill="y", padx=(0,6))
        col_izq.pack_propagate(False)
        self._build_controles(col_izq)

        col_der = tk.Frame(body, bg=PANEL)
        col_der.pack(side="left", fill="both", expand=True)
        self._build_grafica(col_der)

    def _build_controles(self, parent):
        # Canvas con scrollbar
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _sec(parent, titulo, color):
            f = tk.Frame(parent, bg=PANEL2, padx=10, pady=7)
            f.pack(fill="x", pady=(0,4))
            tk.Frame(f, bg=color, height=2).pack(fill="x", pady=(0,5))
            tk.Label(f, text=titulo, bg=PANEL2, fg=color,
                     font=("Georgia", 8, "bold")).pack(anchor="w")
            return f

        def _campo(parent, lbl, var, ancho=16):
            row = tk.Frame(parent, bg=PANEL2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, bg=PANEL2, fg=TXT,
                     font=FN_SM, width=16, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var, width=ancho,
                     font=("Courier New", 8), bg=PANEL, fg=TXT,
                     insertbackground=PURPLE,
                     relief="flat", bd=2).pack(side="left", padx=2)

        # Datos calibración
        s1 = _sec(inner, "DATOS DE CALIBRACIÓN", PURPLE)
        _campo(s1, "OT / Referencia:", self.ot_var)
        # Operador con combo
        row_op = tk.Frame(s1, bg=PANEL2)
        row_op.pack(fill="x", pady=2)
        tk.Label(row_op, text="Operador:", bg=PANEL2, fg=TXT,
                 font=FN_SM, width=16, anchor="w").pack(side="left")
        ops = cargar_operadores()
        self.combo_op = ttk.Combobox(row_op, textvariable=self.operador_var,
                                     values=ops, width=14,
                                     font=("Courier New", 8))
        self.combo_op.pack(side="left", padx=2)
        _campo(s1, "Instrumento:", self.instrumento_var)
        # RUC cliente con consulta SUNAT
        row_ruc = tk.Frame(s1, bg=PANEL2)
        row_ruc.pack(fill="x", pady=2)
        tk.Label(row_ruc, text="RUC cliente:", bg=PANEL2, fg=TXT,
                 font=FN_SM, width=16, anchor="w").pack(side="left")
        self.ruc_var = tk.StringVar(value="")
        tk.Entry(row_ruc, textvariable=self.ruc_var, width=12,
                 font=("Courier New", 8), bg=PANEL, fg=TXT,
                 insertbackground=PURPLE,
                 relief="flat", bd=2).pack(side="left", padx=2)
        tk.Button(row_ruc, text="🔍",
                  bg=PANEL2, fg=ACCENT,
                  font=("Georgia", 9), relief="flat", padx=4,
                  command=self._consultar_sunat).pack(side="left", padx=2)
        self.lbl_razon = tk.Label(s1, text="",
                                   bg=PANEL2, fg=GREEN,
                                   font=("Courier New", 7),
                                   wraplength=250, justify="left")
        self.lbl_razon.pack(anchor="w", pady=(0,2))

        # Certificados equipos
        s2 = _sec(inner, "CERTIFICADOS EQUIPOS", ACCENT)
        _campo(s2, "Cert. HOBO:", self.cert_hobo_var)
        _campo(s2, "Venc. HOBO:", self.venc_hobo_var)
        _campo(s2, "Cert. Yowexa:", self.cert_yowexa_var)
        _campo(s2, "Venc. Yowexa:", self.venc_yowexa_var)

        # Densidad del aire — calculada automáticamente
        # Panel densidad del aire
        # Sección correcciones por trazabilidad
        s_corr = _sec(inner, "CORRECCIONES POR TRAZABILIDAD", RED)
        tk.Label(s_corr,
                 text="Datos del certificado de calibracion",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", pady=(0,3))
        tk.Button(s_corr,
                  text="⚙  Editar correcciones HOBO / Yowexa",
                  bg=RED, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=6, pady=4,
                  command=self._abrir_editor_correcciones).pack(fill="x", pady=2)
        self.lbl_corr_estado = tk.Label(s_corr,
                                        text="Sin correcciones cargadas",
                                        bg=PANEL2, fg=TXT_DIM,
                                        font=("Courier New", 7),
                                        wraplength=250, justify="left")
        self.lbl_corr_estado.pack(anchor="w", pady=2)

        # Condiciones inicio / fin — ingreso manual
        s4 = _sec(inner, "CONDICIONES INICIO / FIN", YELLOW)
        tk.Label(s4, text="T, HR y P ingresados manualmente",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w")
        tk.Label(s4, text="Hora registrada automaticamente",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", pady=(0,4))
        self.lbl_inicio = tk.Label(s4,
                                   text="INICIO: no registrado",
                                   bg=PANEL2, fg=TXT_DIM,
                                   font=("Courier New", 8),
                                   wraplength=250, justify="left")
        self.lbl_inicio.pack(anchor="w", pady=2)
        tk.Button(s4, text="📍  Registrar INICIO",
                  bg=TEAL, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=6, pady=4,
                  command=self._registrar_inicio).pack(fill="x", pady=2)
        self.lbl_fin = tk.Label(s4,
                                text="FIN: no registrado",
                                bg=PANEL2, fg=TXT_DIM,
                                font=("Courier New", 8),
                                wraplength=250, justify="left")
        self.lbl_fin.pack(anchor="w", pady=2)
        tk.Button(s4, text="📍  Registrar FIN",
                  bg=ORANGE, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=6, pady=4,
                  command=self._registrar_fin).pack(fill="x", pady=2)

        # Estado OIML
        s5 = _sec(inner, "ESTADO OIML R111 M2", YELLOW)
        # Fila T inicio / fin
        row_t = tk.Frame(s5, bg=PANEL2); row_t.pack(fill="x", pady=1)
        tk.Label(row_t, text="T:", bg=PANEL2, fg=TXT, font=("Courier New",7), width=3).pack(side="left")
        self.lbl_t_ini = tk.Label(row_t, text="ini: —", bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_t_ini.pack(side="left", padx=(0,6))
        self.lbl_t_fin = tk.Label(row_t, text="fin: —", bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_t_fin.pack(side="left")
        # Fila HR inicio / fin
        row_h = tk.Frame(s5, bg=PANEL2); row_h.pack(fill="x", pady=1)
        tk.Label(row_h, text="HR:", bg=PANEL2, fg=TXT, font=("Courier New",7), width=3).pack(side="left")
        self.lbl_hr_ini = tk.Label(row_h, text="ini: —", bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_hr_ini.pack(side="left", padx=(0,6))
        self.lbl_hr_fin = tk.Label(row_h, text="fin: —", bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_hr_fin.pack(side="left")
        # Variación
        self.lbl_v1  = tk.Label(s5, text="Var 1h: —",    bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_v12 = tk.Label(s5, text="Var total: —", bg=PANEL2, fg=TXT_DIM, font=("Courier New",8))
        self.lbl_v1.pack(anchor="w", pady=1)
        self.lbl_v12.pack(anchor="w", pady=1)
        # Estado global
        self.lbl_oiml_global = tk.Label(s5, text="— Sin registros —",
                                         bg=PANEL2, fg=TXT_DIM,
                                         font=("Georgia", 8, "bold"))
        self.lbl_oiml_global.pack(anchor="w", pady=(3,0))
        # Alias para compatibilidad con _procesar_csv
        self.lbl_t_est  = self.lbl_t_ini
        self.lbl_hr_est = self.lbl_hr_ini

        # Densidad del aire — debajo del estado OIML
        sec_rho = _sec(inner, "DENSIDAD DEL AIRE", TEAL)
        tk.Label(sec_rho,
                 text="Calculada con T, HR y P corregidos (Lagrange)",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w")
        self.lbl_densidad = tk.Label(sec_rho, text="rho: —",
                                     bg=PANEL2, fg=TEAL,
                                     font=("Courier New", 10, "bold"))
        self.lbl_densidad.pack(anchor="w", pady=3)
        self.lbl_densidad_detalle = tk.Label(sec_rho,
                                             text="T: —  HR: —  P: —",
                                             bg=PANEL2, fg=TXT_DIM,
                                             font=("Courier New", 7))
        self.lbl_densidad_detalle.pack(anchor="w")
        self.lbl_empuje = tk.Label(sec_rho,
                                   text="Empuje del aire: —",
                                   bg=PANEL2, fg=TXT_DIM,
                                   font=("Georgia", 7, "bold"))
        self.lbl_empuje.pack(anchor="w", pady=(2,0))
        tk.Label(sec_rho,
                 text="ref: 1,1839 kg/m3 (20°C / 50% / 1013 mbar)",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Courier New", 7)).pack(anchor="w")

        # HOBO — descarga mensual
        s6 = _sec(inner, "HOBO — DESCARGA MENSUAL", GREEN)
        tk.Label(s6,
                 text="El HOBO contrasta los datos manuales.",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w")
        tk.Label(s6,
                 text="Descarga 1 vez al mes para informe.",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", pady=(0,4))
        self.lbl_vigilando = tk.Label(s6, text="",
                                      bg=PANEL2, fg=TXT_DIM,
                                      font=("Courier New", 7))
        self.lbl_vigilando.pack(anchor="w")
        tk.Button(s6, text="📥  Cargar CSV del HOBO",
                  bg=GREEN, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=6, pady=5,
                  command=self._cargar_csv_manual).pack(fill="x", pady=2)
        self.lbl_csv = tk.Label(s6, text="Sin datos HOBO cargados",
                                bg=PANEL2, fg=TXT_DIM,
                                font=("Courier New", 7),
                                wraplength=250, justify="left")
        self.lbl_csv.pack(anchor="w", pady=2)

        # Botones documentos
        s7 = _sec(inner, "DOCUMENTOS", PURPLE)
        # Nota: condiciones ambientales incluidas en PDF del ensayo ABA (HTA-001)
        tk.Label(s7,
                 text="Condiciones incluidas en PDF del ensayo ABA",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", pady=(0,3))
        tk.Button(s7,
                  text="📊  INFORME MENSUAL PDF",
                  bg=ACCENT2, fg="white",
                  font=("Georgia", 9, "bold"),
                  relief="flat", padx=6, pady=5,
                  command=self._generar_informe_mensual).pack(fill="x", pady=2)
        tk.Button(s7,
                  text="🖼  Exportar gráfica PNG",
                  bg=PANEL, fg=TXT,
                  font=FN_SM, relief="flat", padx=6, pady=3,
                  command=self._exportar_grafica).pack(fill="x", pady=1)

    def _build_grafica(self, parent):
        tk.Label(parent, text="  Temperatura y Humedad — Registros manuales + HOBO UX100-011A",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(anchor="w", padx=8, pady=4)
        self.fig = Figure(figsize=(6, 4), facecolor='#0f1828')
        self.fig.subplots_adjust(left=0.08, right=0.93,
                                 top=0.88, bottom=0.14, hspace=0.4)
        self.ax_t = self.fig.add_subplot(211)
        self.ax_h = self.fig.add_subplot(212)
        for ax in [self.ax_t, self.ax_h]:
            ax.set_facecolor('#141f2e')
            ax.tick_params(colors='#4a6480', labelsize=7)
            for sp in ax.spines.values():
                sp.set_color('#1a2940')
            ax.grid(True, alpha=0.2, color='#1a2940')
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    def _get_ultima_lectura(self):
        if self.df_hobo is None or len(self.df_hobo) == 0:
            return None
        return self.df_hobo.iloc[-1]

    def _actualizar_estado_correcciones(self):
        """Muestra resumen de correcciones cargadas."""
        corr = self.correcciones
        pts_t = len(corr.get("hobo_temp", []))
        pts_h = len(corr.get("hobo_hr",   []))
        pts_p = len(corr.get("yowexa_presion", []))
        # Verificar si hay correcciones no nulas
        tiene_corr = any(
            abs(p.get("correccion", 0)) > 0.0001
            for lista in [corr.get("hobo_temp",[]),
                          corr.get("hobo_hr",[]),
                          corr.get("yowexa_presion",[])]
            for p in lista
        )
        if tiene_corr:
            self.lbl_corr_estado.config(
                text=f"Correcciones activas:\n"
                     f"T: {pts_t} puntos | HR: {pts_h} puntos | P: {pts_p} punto(s)\n"
                     f"U_T={corr.get('u_temp',0.21)}°C  "
                     f"U_HR={corr.get('u_hr',2.5)}%  "
                     f"U_P={corr.get('u_presion',1.0)} mbar",
                fg=GREEN)
        else:
            self.lbl_corr_estado.config(
                text="Sin correcciones aplicadas (todos en cero)",
                fg=YELLOW)

    def _abrir_editor_correcciones(self):
        """Ventana para editar correcciones del certificado."""
        if not _verificar_password(self):
            return
        win = tk.Toplevel(self)
        win.title("Correcciones por Trazabilidad — Certificados")
        win.geometry("680x620")
        win.configure(bg=PANEL)
        win.grab_set()

        tk.Frame(win, bg=RED, height=3).pack(fill="x")
        tk.Label(win,
                 text="CORRECCIONES POR TRAZABILIDAD — NMP 004:2007 / ISO 17025",
                 bg=PANEL, fg=RED,
                 font=("Georgia", 10, "bold")).pack(pady=(10,2))
        tk.Label(win,
                 text="Ingresa los datos de los certificados de calibración de cada equipo",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(pady=(0,8))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=10, pady=5)

        # ── Pestaña Temperatura ───────────────────────────────
        tab_t = tk.Frame(nb, bg=PANEL)
        nb.add(tab_t, text="  Temperatura (HOBO)  ")
        self._tab_correcciones(tab_t, "hobo_temp",
                               "Temperatura",
                               ["Indicación HOBO (°C)", "Corrección F(X) (°C)"],
                               "u_temp", "°C")

        # ── Pestaña Humedad ───────────────────────────────────
        tab_h = tk.Frame(nb, bg=PANEL)
        nb.add(tab_h, text="  Humedad Relativa (HOBO)  ")
        self._tab_correcciones(tab_h, "hobo_hr",
                               "Humedad Relativa",
                               ["Indicación HOBO (%)", "Corrección F(X) (%)"],
                               "u_hr", "%")

        # ── Pestaña Presión ───────────────────────────────────
        tab_p = tk.Frame(nb, bg=PANEL)
        nb.add(tab_p, text="  Presión (Yowexa)  ")
        self._tab_correcciones(tab_p, "yowexa_presion",
                               "Presión Atmosférica",
                               ["Indicación Yowexa (mbar)", "Corrección F(X) (mbar)"],
                               "u_presion", "mbar")

        # Botón guardar
        def guardar():
            guardar_correcciones(self.correcciones)
            self._actualizar_estado_correcciones()
            messagebox.showinfo("✓ Guardado",
                                "Correcciones guardadas.\n"
                                "Se aplicarán en el próximo registro.",
                                parent=win)
            win.destroy()

        tk.Button(win, text="✔  Guardar correcciones",
                  bg=GREEN, fg="white",
                  font=("Georgia", 10, "bold"),
                  relief="flat", padx=20, pady=6,
                  command=guardar).pack(pady=8)

    def _tab_correcciones(self, parent, clave, titulo, col_labels, clave_u, unidad):
        """Construye una pestaña de edición de puntos de corrección."""
        tk.Frame(parent, bg=PANEL2, height=1).pack(fill="x")
        tk.Label(parent,
                 text=f"  Puntos de calibración — {titulo}",
                 bg=PANEL, fg=TXT,
                 font=("Georgia", 9, "bold")).pack(anchor="w", padx=10, pady=8)
        tk.Label(parent,
                 text="  X = Indicación del instrumento  |  F(X) = Corrección = VCV - Lectura",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", padx=10)

        # Tabla de puntos
        frame_tabla = tk.Frame(parent, bg=PANEL)
        frame_tabla.pack(fill="x", padx=10, pady=8)

        # Encabezados — X (Indicacion) y F(X) (Correccion)
        for j, col in enumerate(col_labels + ["Acción"]):
            tk.Label(frame_tabla, text=col, bg=PANEL2, fg=ACCENT,
                     font=("Georgia", 8, "bold"),
                     width=18, relief="flat", padx=4).grid(
                         row=0, column=j, padx=1, pady=1, sticky="ew")

        puntos = self.correcciones.get(clave, [])
        filas_vars = []

        def refrescar():
            for w in frame_tabla.grid_slaves():
                if int(w.grid_info()["row"]) > 0:
                    w.destroy()
            filas_vars.clear()
            for i, pt in enumerate(puntos):
                vars_fila = {}
                for j, key in enumerate(["lectura", "correccion"]):
                    # Mostrar con coma decimal
                    val_raw = pt.get(key, 0.0)
                    val_str = str(val_raw).replace(".", ",") if isinstance(val_raw, float) else str(val_raw)
                    var = tk.StringVar(value=val_str)
                    e = _entry_coma(frame_tabla, var,
                                    width=16, font=("Courier New", 9),
                                    bg=PANEL2, fg=TXT,
                                    insertbackground=ACCENT,
                                    relief="flat", bd=2)
                    e.grid(row=i+1, column=j, padx=1, pady=1)
                    vars_fila[key] = var
                # Botón eliminar
                def del_row(idx=i):
                    puntos.pop(idx)
                    self.correcciones[clave] = puntos
                    refrescar()
                tk.Button(frame_tabla, text="✕", bg="#7f1d1d", fg="white",
                          font=("Georgia", 8), relief="flat", padx=4,
                          command=del_row).grid(row=i+1, column=3, padx=1, pady=1)
                filas_vars.append(vars_fila)

        def guardar_filas():
            nuevos = []
            for vars_fila in filas_vars:
                try:
                    lect = float(vars_fila["lectura"].get().replace(",","."))
                    corr = float(vars_fila["correccion"].get().replace(",","."))
                    nuevos.append({
                        "nominal":    lect + corr,  # VCV = lectura + correccion
                        "lectura":    lect,
                        "correccion": corr,
                    })
                except ValueError:
                    pass
            self.correcciones[clave] = nuevos

        def agregar():
            guardar_filas()
            puntos.append({"nominal": 0.0, "lectura": 0.0, "correccion": 0.0})
            self.correcciones[clave] = puntos
            refrescar()

        refrescar()

        tk.Button(parent, text="➕  Agregar punto",
                  bg=ACCENT2, fg="white",
                  font=("Georgia", 8), relief="flat", padx=8, pady=3,
                  command=agregar).pack(anchor="w", padx=10, pady=4)

        # Incertidumbre expandida
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=4)
        row_u = tk.Frame(parent, bg=PANEL)
        row_u.pack(anchor="w", padx=10, pady=4)
        tk.Label(row_u,
                 text=f"Incertidumbre expandida U (k=2): ",
                 bg=PANEL, fg=TXT,
                 font=("Georgia", 8)).pack(side="left")
        val_u = self.correcciones.get(clave_u, 0.0)
        var_u = tk.StringVar(value=str(val_u).replace(".", ","))
        _entry_coma(row_u, var_u, width=8,
                    font=("Courier New", 9, "bold"),
                    bg=PANEL2, fg=ACCENT,
                    insertbackground=ACCENT,
                    relief="flat", bd=2).pack(side="left", padx=4)
        tk.Label(row_u, text=unidad, bg=PANEL, fg=TXT,
                 font=("Georgia", 8)).pack(side="left")

        def sync_u(*args):
            try:
                self.correcciones[clave_u] = float(var_u.get().replace(",","."))
            except: pass
        var_u.trace("w", sync_u)

        # Nota interpolación
        tk.Label(parent,
                 text="  Polinomio de Lagrange (igual al modelo Excel Metromecanica). Extrapolación constante en extremos.",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w", padx=10, pady=2)

        # Vincular guardar filas al cambiar de pestaña
        parent.bind("<FocusOut>", lambda e: guardar_filas())

    def _abrir_dialogo_condicion(self, tipo):
        """Diálogo para ingreso manual de condiciones ambientales."""
        win = tk.Toplevel(self)
        win.title(f"Registrar condicion {tipo.upper()}")
        win.geometry("360x280")
        win.configure(bg=PANEL)
        win.grab_set()

        color = TEAL if tipo == "inicio" else ORANGE
        tk.Frame(win, bg=color, height=3).pack(fill="x")
        tk.Label(win, text=f"CONDICION {tipo.upper()} — Ingreso Manual",
                 bg=PANEL, fg=color,
                 font=("Georgia", 10, "bold")).pack(pady=(10,5))
        tk.Label(win,
                 text=f"Hora de registro: {datetime.now().strftime('%H:%M:%S')}",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Courier New", 8)).pack()
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", pady=6)

        campos_var = {}
        campos_def = [
            ("Temperatura (°C):", "temp", ""),
            ("Humedad Relativa (%):", "hr", ""),
            ("Presion atm. (mbar):", "presion", self.presion_var.get()),  # 1 hPa = 1 mbar
        ]
        for lbl_txt, key, default in campos_def:
            row = tk.Frame(win, bg=PANEL, padx=20)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=lbl_txt, bg=PANEL, fg=TXT,
                     font=FN_UI, width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(default).replace('.',',') if default else '')
            _entry_coma(row, var, width=10,
                        font=("Courier New", 11, "bold"),
                        bg=PANEL2, fg=color,
                        insertbackground=color,
                        relief="flat", bd=3).pack(side="left")
            campos_var[key] = var

        result = [None]
        def confirmar():
            try:
                t = float(campos_var["temp"].get().replace(",","."))
                h = float(campos_var["hr"].get().replace(",","."))
                p = float(campos_var["presion"].get().replace(",","."))
                result[0] = {
                    "temp":    t,
                    "hr":      h,
                    "presion": p,
                    "hora":    datetime.now().strftime("%H:%M:%S"),
                    "fecha":   datetime.now().strftime("%d/%m/%Y"),
                }
                win.destroy()
            except ValueError:
                messagebox.showerror("Error",
                    "Ingresa valores numéricos válidos.", parent=win)

        tk.Button(win, text=f"✓  Confirmar {tipo}",
                  bg=color, fg="white",
                  font=("Georgia", 10, "bold"),
                  relief="flat", padx=16, pady=6,
                  command=confirmar).pack(pady=12)
        win.wait_window()
        return result[0]

    def _registrar_inicio(self):
        datos = self._abrir_dialogo_condicion("inicio")
        if datos is None:
            return
        self.cond_inicio = datos
        self.presion_var.set(str(datos["presion"]))
        self.lbl_inicio.config(
            text=f"INICIO ({datos['hora']}): T={datos['temp']:.2f}°C HR={datos['hr']:.1f}% P={datos['presion']} mbar".replace('.',','),
            fg=TEAL)
        corr_result = aplicar_correcciones(
            datos['temp'], datos['hr'], datos['presion'], self.correcciones)
        datos['corr'] = corr_result
        registrar_log("CONDICION_INICIO", self.operador_var.get(),
                      f"T={datos['temp']}({corr_result['t_corr']}) "
                      f"HR={datos['hr']}({corr_result['h_corr']}) "
                      f"P={datos['presion']}({corr_result['p_corr']})")
        rho_txt, emp_txt, rho_col, emp_col = _fmt_rho(corr_result['rho_corr'])
        self.lbl_densidad.config(text=rho_txt, fg=rho_col)
        if hasattr(self, 'lbl_densidad_detalle'):
            det = (f"T={corr_result['t_corr']:.4f}°C  HR={corr_result['h_corr']:.4f}%  P={corr_result['p_corr']:.2f} mbar").replace(".",",")
            self.lbl_densidad_detalle.config(text=det, fg=TXT_DIM)
        if hasattr(self, 'lbl_empuje'):
            self.lbl_empuje.config(text=emp_txt, fg=emp_col)
        self.registros_manuales.append({
            'tipo': 'INICIO', 'ts': datetime.now(),
            'temp': datos['temp'], 'hr': datos['hr'],
            'presion': datos['presion'], 'ot': self.ot_var.get(),
            'corr': corr_result
        })
        self._actualizar_grafica_manual()
        self._actualizar_oiml_manual()
        # Sincronizar panel superior ABA
        app = getattr(self, '_app_ref', None)
        if app and hasattr(app, '_actualizar_panel_cond_aba'):
            app._actualizar_panel_cond_aba()

    def _registrar_fin(self):
        datos = self._abrir_dialogo_condicion("fin")
        if datos is None:
            return
        self.cond_fin = datos
        self.presion_var.set(str(datos["presion"]))
        self.lbl_fin.config(
            text=f"FIN ({datos['hora']}): T={datos['temp']:.2f}°C HR={datos['hr']:.1f}% P={datos['presion']} mbar".replace('.',','),
            fg=ORANGE)
        corr_result = aplicar_correcciones(
            datos['temp'], datos['hr'], datos['presion'], self.correcciones)
        datos['corr'] = corr_result
        registrar_log("CONDICION_FIN", self.operador_var.get(),
                      f"T={datos['temp']}({corr_result['t_corr']}) "
                      f"HR={datos['hr']}({corr_result['h_corr']}) "
                      f"P={datos['presion']}({corr_result['p_corr']})")
        rho_txt, emp_txt, rho_col, emp_col = _fmt_rho(corr_result['rho_corr'])
        self.lbl_densidad.config(text=rho_txt, fg=rho_col)
        if hasattr(self, 'lbl_densidad_detalle'):
            det = (f"T={corr_result['t_corr']:.4f}°C  HR={corr_result['h_corr']:.4f}%  P={corr_result['p_corr']:.2f} mbar").replace(".",",")
            self.lbl_densidad_detalle.config(text=det, fg=TXT_DIM)
        if hasattr(self, 'lbl_empuje'):
            self.lbl_empuje.config(text=emp_txt, fg=emp_col)
        self.registros_manuales.append({
            'tipo': 'FIN', 'ts': datetime.now(),
            'temp': datos['temp'], 'hr': datos['hr'],
            'presion': datos['presion'], 'ot': self.ot_var.get(),
            'corr': corr_result
        })
        self._actualizar_grafica_manual()
        self._actualizar_oiml_manual()
        # Sincronizar panel superior ABA
        app = getattr(self, '_app_ref', None)
        if app and hasattr(app, '_actualizar_panel_cond_aba'):
            app._actualizar_panel_cond_aba()

    def _toggle_vigilancia(self):
        if self.vigilando: self._detener_vigilancia()
        else: self._iniciar_vigilancia()

    def _iniciar_vigilancia(self):
        try:
            carpeta = CARPETA_HOBO.replace("\\\\","\\")
            if not os.path.exists(carpeta):
                carpeta = filedialog.askdirectory(
                    title="Seleccionar carpeta HOBOware")
                if not carpeta: return
            handler = _HOBOWatcher(self)
            self.observer = Observer()
            self.observer.schedule(handler, path=carpeta, recursive=False)
            self.observer.start()
            self.vigilando = True
            self.btn_vigilar.config(text="⏹ Detener", bg=RED)
            self.lbl_vigilando.config(text=f"● {carpeta[:30]}", fg=GREEN)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _detener_vigilancia(self):
        if self.observer:
            self.observer.stop(); self.observer.join(); self.observer = None
        self.vigilando = False
        self.btn_vigilar.config(text="▶ Iniciar vigilancia CSV", bg=GREEN)
        self.lbl_vigilando.config(text="Inactivo", fg=TXT_DIM)

    def _cargar_csv_manual(self):
        ruta = filedialog.askopenfilename(
            title="Seleccionar CSV HOBOware",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")])
        if ruta: self._procesar_csv(ruta)

    def _procesar_csv(self, filepath):
        df = parsear_csv_hobo(filepath)
        if df is None or len(df) == 0:
            self.lbl_csv.config(text="Error al leer CSV", fg=RED)
            return
        self.df_hobo = df
        self.lbl_csv.config(
            text=f"✓ {os.path.basename(filepath)}\n{len(df)} registros",
            fg=GREEN)
        # Registrar fecha de descarga para alarma mensual
        cfg = cargar_config()
        cfg["ultima_descarga_hobo"] = datetime.now().strftime("%Y-%m-%d")
        guardar_config(cfg)
        registrar_log("DESCARGA_HOBO", self.operador_var.get(),
                      f"{os.path.basename(filepath)} — {len(df)} registros")
        try: presion = float(self.presion_var.get().replace(",","."))
        except: presion = 1014.3

        u = df.iloc[-1]
        df_1h  = df[df['timestamp'] >= u['timestamp'] - pd.Timedelta(hours=1)]
        df_12h = df[df['timestamp'] >= u['timestamp'] - pd.Timedelta(hours=12)]
        v1  = df_1h['temp_c'].max()  - df_1h['temp_c'].min()  if len(df_1h)>=2  else 0
        v12 = df_12h['temp_c'].max() - df_12h['temp_c'].min() if len(df_12h)>=2 else 0

        t_ok   = TEMP_MIN <= u['temp_c'] <= TEMP_MAX
        hr_ok  = pd.notna(u['hr_pct']) and u['hr_pct'] <= HR_MAX
        v1_ok  = v1  <= VAR_MAX_1H
        v12_ok = v12 <= VAR_MAX_12H

        # Actualizar OIML desde CSV del HOBO
        self.lbl_t_ini.config(
            text=f"HOBO: {u['temp_c']:.2f}°C {'✓' if t_ok else '⚠'}".replace(".",","),
            fg=GREEN if t_ok else RED)
        self.lbl_t_fin.config(text="", fg=TXT_DIM)
        self.lbl_hr_ini.config(
            text=f"HOBO: {u['hr_pct']:.1f}% {'✓' if hr_ok else '⚠'}".replace(".",","),
            fg=GREEN if hr_ok else RED)
        self.lbl_hr_fin.config(text="", fg=TXT_DIM)
        self.lbl_v1.config(
            text=f"Var 1h: {v1:.2f}°C (lim ±{VAR_MAX_1H}) {'✓' if v1_ok else '⚠'}".replace(".",","),
            fg=GREEN if v1_ok else RED)
        self.lbl_v12.config(
            text=f"Var 12h: {v12:.2f}°C (lim ±{VAR_MAX_12H}) {'✓' if v12_ok else '⚠'}".replace(".",","),
            fg=GREEN if v12_ok else RED)
        todas_ok_csv = t_ok and hr_ok and v1_ok and v12_ok
        self.lbl_oiml_global.config(
            text="✓ CONFORME — OIML R111 M2" if todas_ok_csv else "⚠ NO CONFORME — REVISAR",
            fg=GREEN if todas_ok_csv else RED)

        # Densidad con corrección Lagrange sobre última lectura del HOBO
        corr_hobo = aplicar_correcciones(
            float(u['temp_c']), float(u['hr_pct']), presion, self.correcciones)
        rho = corr_hobo.get('rho_corr')
        self.lbl_densidad.config(
            text=f"rho: {str(rho).replace('.',',')} kg/m3 (corregido)" if rho else "rho: —",
            fg=TEAL)

        self.lbl_banner.config(
            text="✓ CONDICIONES OK" if all([t_ok,hr_ok,v1_ok,v12_ok]) else "⚠ ALERTA",
            fg=GREEN if all([t_ok,hr_ok,v1_ok,v12_ok]) else RED)

        self._actualizar_grafica(df)

    def _actualizar_oiml_manual(self):
        """Actualiza estado OIML con valores CORREGIDOS por trazabilidad."""
        if not self.registros_manuales:
            return

        # Separar inicio y fin
        inics = [r for r in self.registros_manuales if r['tipo'] == 'INICIO']
        fins  = [r for r in self.registros_manuales if r['tipo'] == 'FIN']
        ultimo_ini = inics[-1] if inics else None
        ultimo_fin = fins[-1]  if fins  else None

        def t_corr(r):
            """Retorna T corregida si existe, bruta si no."""
            c = r.get('corr', {})
            return c.get('t_corr', r['temp']) if c else r['temp']

        def h_corr(r):
            c = r.get('corr', {})
            return c.get('h_corr', r['hr']) if c else r['hr']

        # Usar valores corregidos para verificación OIML
        todos_temps = [t_corr(r) for r in self.registros_manuales]
        todos_hrs   = [h_corr(r) for r in self.registros_manuales]

        # Verificar todos dentro del rango (con valores corregidos)
        t_todos_ok  = all(TEMP_MIN <= t <= TEMP_MAX for t in todos_temps)
        hr_todos_ok = all(h <= HR_MAX for h in todos_hrs)

        # Variación con valores corregidos
        ahora = datetime.now()
        r_1h  = [r for r in self.registros_manuales
                 if (ahora - r['ts']).total_seconds() <= 3600]
        v1h   = (max(t_corr(r) for r in r_1h) -
                 min(t_corr(r) for r in r_1h)) if len(r_1h) > 1 else 0
        v_total = max(todos_temps) - min(todos_temps) if len(todos_temps) > 1 else 0
        v1_ok  = v1h    <= VAR_MAX_1H
        v12_ok = v_total <= VAR_MAX_12H

        # Mostrar T inicio y fin (valores corregidos)
        if ultimo_ini:
            t_i   = t_corr(ultimo_ini)
            ok_i  = TEMP_MIN <= t_i <= TEMP_MAX
            tiene_corr_i = abs(t_i - ultimo_ini['temp']) > 0.0001
            etiq_i = f"ini: {t_i:.4f}°C {'✓' if ok_i else '⚠'}"
            if tiene_corr_i:
                etiq_i += f" (corr)"
            self.lbl_t_ini.config(
                text=etiq_i.replace(".",","),
                fg=GREEN if ok_i else RED)
        if ultimo_fin:
            t_f   = t_corr(ultimo_fin)
            ok_f  = TEMP_MIN <= t_f <= TEMP_MAX
            tiene_corr_f = abs(t_f - ultimo_fin['temp']) > 0.0001
            etiq_f = f"fin: {t_f:.4f}°C {'✓' if ok_f else '⚠'}"
            if tiene_corr_f:
                etiq_f += f" (corr)"
            self.lbl_t_fin.config(
                text=etiq_f.replace(".",","),
                fg=GREEN if ok_f else RED)

        # Mostrar HR inicio y fin (valores corregidos)
        if ultimo_ini:
            h_i   = h_corr(ultimo_ini)
            ok_hi = h_i <= HR_MAX
            tiene_corr_hi = abs(h_i - ultimo_ini['hr']) > 0.001
            etiq_hi = f"ini: {h_i:.2f}% {'✓' if ok_hi else '⚠'}"
            if tiene_corr_hi:
                etiq_hi += " (corr)"
            self.lbl_hr_ini.config(
                text=etiq_hi.replace(".",","),
                fg=GREEN if ok_hi else RED)
        if ultimo_fin:
            h_f   = h_corr(ultimo_fin)
            ok_hf = h_f <= HR_MAX
            tiene_corr_hf = abs(h_f - ultimo_fin['hr']) > 0.001
            etiq_hf = f"fin: {h_f:.2f}% {'✓' if ok_hf else '⚠'}"
            if tiene_corr_hf:
                etiq_hf += " (corr)"
            self.lbl_hr_fin.config(
                text=etiq_hf.replace(".",","),
                fg=GREEN if ok_hf else RED)

        # Variaciones con valores corregidos
        self.lbl_v1.config(
            text=f"Var 1h: {v1h:.4f}°C (lim ±{VAR_MAX_1H}) {'✓' if v1_ok else '⚠'}".replace(".",","),
            fg=GREEN if v1_ok else RED)
        self.lbl_v12.config(
            text=f"Var ini-fin: {v_total:.4f}°C (lim ±{VAR_MAX_12H}) {'✓' if v12_ok else '⚠'}".replace(".",","),
            fg=GREEN if v12_ok else RED)

        # Estado global
        todas_ok = t_todos_ok and hr_todos_ok and v1_ok and v12_ok
        self.lbl_oiml_global.config(
            text="✓ CONFORME — OIML R111 M2" if todas_ok else "⚠ NO CONFORME — REVISAR",
            fg=GREEN if todas_ok else RED)
        self.lbl_banner.config(
            text="✓ CONDICIONES OK — OIML R111 M2" if todas_ok else "⚠ ALERTA — REVISAR CONDICIONES",
            fg=GREEN if todas_ok else RED)

    def _actualizar_grafica_manual(self):
        """Grafica puntos manuales de inicio/fin acumulados en el mes."""
        if not self.registros_manuales:
            return
        # Si hay CSV del HOBO, actualizar también esa gráfica
        if self.df_hobo is not None:
            self._actualizar_grafica(self.df_hobo)
            return

        # Sin CSV del HOBO — graficar solo puntos manuales
        self.ax_t.clear(); self.ax_h.clear()
        for ax in [self.ax_t, self.ax_h]:
            ax.set_facecolor('#141f2e')
            ax.tick_params(colors='#4a6480', labelsize=7)
            for sp in ax.spines.values(): sp.set_color('#1a2940')
            ax.grid(True, alpha=0.2, color='#1a2940')

        ts_list   = [r['ts']   for r in self.registros_manuales]
        temp_list = [r['temp'] for r in self.registros_manuales]
        hr_list   = [r['hr']   for r in self.registros_manuales]
        tipos     = [r['tipo'] for r in self.registros_manuales]

        # Colores por tipo
        colores = ['#00c8e0' if t == 'INICIO' else '#f97316' for t in tipos]

        # Temperatura
        self.ax_t.axhspan(TEMP_MIN, TEMP_MAX, alpha=0.08, color='#22c55e')
        self.ax_t.axhline(TEMP_MIN, color='#ef4444', lw=1, ls='--', alpha=0.7)
        self.ax_t.axhline(TEMP_MAX, color='#ef4444', lw=1, ls='--', alpha=0.7)
        self.ax_t.plot(ts_list, temp_list, color='#e74c3c', lw=1, ls='--', alpha=0.4)
        for ts, t, c, tipo in zip(ts_list, temp_list, colores, tipos):
            self.ax_t.scatter(ts, t, color=c, s=40, zorder=5)
        self.ax_t.set_ylabel('°C', color='#e74c3c', fontsize=8)
        self.ax_t.tick_params(axis='y', labelcolor='#e74c3c')
        ult_t = temp_list[-1]
        self.ax_t.set_title(
            f"T manual — Ultimo: {ult_t:.2f}°C  ({len(self.registros_manuales)} registros)",
            color=TXT, fontsize=8, pad=4)

        # Humedad
        self.ax_h.axhspan(0, HR_MAX, alpha=0.05, color='#2980b9')
        self.ax_h.axhline(HR_MAX, color='#2980b9', lw=1, ls='--', alpha=0.7)
        self.ax_h.plot(ts_list, hr_list, color='#2980b9', lw=1, ls='--', alpha=0.4)
        for ts, h, c in zip(ts_list, hr_list, colores):
            self.ax_h.scatter(ts, h, color=c, s=40, zorder=5)
        self.ax_h.set_ylim(0, 100)
        self.ax_h.set_ylabel('% HR', color='#2980b9', fontsize=8)
        self.ax_h.tick_params(axis='y', labelcolor='#2980b9')
        ult_h = hr_list[-1]
        self.ax_h.set_title(
            f"HR manual — Ultimo: {ult_h:.1f}%",
            color=TXT, fontsize=8, pad=4)

        # Leyenda manual
        from matplotlib.lines import Line2D
        legend = [
            Line2D([0],[0], marker='o', color='w', markerfacecolor='#00c8e0',
                   markersize=6, label='INICIO'),
            Line2D([0],[0], marker='o', color='w', markerfacecolor='#f97316',
                   markersize=6, label='FIN'),
        ]
        self.ax_t.legend(handles=legend, fontsize=6, loc='upper right')

        for ax in [self.ax_t, self.ax_h]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m\n%H:%M'))
        self.fig.autofmt_xdate(rotation=20, ha='right')
        self.canvas.draw()

        # Densidad del aire — promedio condiciones inicio y fin
        inics = [r for r in self.registros_manuales if r['tipo'] == 'INICIO']
        fins  = [r for r in self.registros_manuales if r['tipo'] == 'FIN']

        def get_corr(r, key, fallback_key):
            c = r.get('corr', {})
            return c.get(key, r[fallback_key]) if c else r[fallback_key]

        if inics and fins:
            # Promedio inicio + fin (correcto para ISO 17025)
            ri = inics[-1]; rf = fins[-1]
            t_d = (get_corr(ri,'t_corr','temp') + get_corr(rf,'t_corr','temp')) / 2
            h_d = (get_corr(ri,'h_corr','hr')   + get_corr(rf,'h_corr','hr'))   / 2
            p_d = (get_corr(ri,'p_corr','presion') + get_corr(rf,'p_corr','presion')) / 2
            modo = "prom ini+fin"
        elif inics:
            ri = inics[-1]
            t_d = get_corr(ri,'t_corr','temp')
            h_d = get_corr(ri,'h_corr','hr')
            p_d = get_corr(ri,'p_corr','presion')
            modo = "solo INICIO"
        else:
            ult = self.registros_manuales[-1]
            t_d = get_corr(ult,'t_corr','temp')
            h_d = get_corr(ult,'h_corr','hr')
            p_d = get_corr(ult,'p_corr','presion')
            modo = "ultimo reg."

        rho = calcular_densidad_aire(t_d, h_d, p_d)
        detalle = (f"T={t_d:.4f}°C  HR={h_d:.4f}%  P={p_d:.2f} mbar  [{modo}]"
                   .replace(".",","))
        rho_txt, emp_txt, rho_col, emp_col = _fmt_rho(rho)
        self.lbl_densidad.config(text=rho_txt, fg=rho_col)
        if hasattr(self, 'lbl_densidad_detalle'):
            self.lbl_densidad_detalle.config(text=detalle, fg=TXT_DIM)
        if hasattr(self, 'lbl_empuje'):
            self.lbl_empuje.config(text=emp_txt, fg=emp_col)

    def _actualizar_grafica(self, df):
        self.ax_t.clear(); self.ax_h.clear()
        for ax in [self.ax_t, self.ax_h]:
            ax.set_facecolor('#141f2e')
            ax.tick_params(colors='#4a6480', labelsize=7)
            for sp in ax.spines.values(): sp.set_color('#1a2940')
            ax.grid(True, alpha=0.2, color='#1a2940')
        self.ax_t.axhspan(TEMP_MIN, TEMP_MAX, alpha=0.08, color='#22c55e')
        self.ax_t.axhline(TEMP_MIN, color='#ef4444', lw=1, ls='--', alpha=0.7)
        self.ax_t.axhline(TEMP_MAX, color='#ef4444', lw=1, ls='--', alpha=0.7)
        self.ax_t.plot(df['timestamp'], df['temp_c'], color='#e74c3c', lw=1.2)
        self.ax_t.set_ylabel('°C', color='#e74c3c', fontsize=8)
        self.ax_t.tick_params(axis='y', labelcolor='#e74c3c')
        self.ax_t.set_title(
            f"T — Último: {df.iloc[-1]['temp_c']:.2f}°C",
            color=TXT, fontsize=8, pad=4)
        if df['hr_pct'].notna().any():
            self.ax_h.axhspan(0, HR_MAX, alpha=0.05, color='#2980b9')
            self.ax_h.axhline(HR_MAX, color='#2980b9', lw=1, ls='--', alpha=0.7)
            self.ax_h.plot(df['timestamp'], df['hr_pct'], color='#2980b9', lw=1.2)
            self.ax_h.set_ylim(0, 100)
        self.ax_h.set_ylabel('% HR', color='#2980b9', fontsize=8)
        self.ax_h.tick_params(axis='y', labelcolor='#2980b9')
        self.ax_h.set_title(
            f"HR — Último: {df.iloc[-1]['hr_pct']:.1f}%",
            color=TXT, fontsize=8, pad=4)
        self.ax_t.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m\n%H:%M'))
        self.ax_h.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m\n%H:%M'))

        # Superponer puntos manuales si existen
        if self.registros_manuales:
            ts_m  = [r['ts']   for r in self.registros_manuales]
            t_m   = [r['temp'] for r in self.registros_manuales]
            h_m   = [r['hr']   for r in self.registros_manuales]
            tipos = [r['tipo'] for r in self.registros_manuales]
            cols  = ['#00c8e0' if tp == 'INICIO' else '#f97316' for tp in tipos]
            for ts, t, h, c in zip(ts_m, t_m, h_m, cols):
                self.ax_t.scatter(ts, t, color=c, s=55, zorder=6,
                                  edgecolors='white', linewidths=0.5)
                self.ax_h.scatter(ts, h, color=c, s=55, zorder=6,
                                  edgecolors='white', linewidths=0.5)
            from matplotlib.lines import Line2D
            leyenda = [
                Line2D([0],[0], marker='o', color='w',
                       markerfacecolor='#00c8e0', markersize=7, label='Manual INICIO'),
                Line2D([0],[0], marker='o', color='w',
                       markerfacecolor='#f97316', markersize=7, label='Manual FIN'),
            ]
            self.ax_t.legend(handles=leyenda, fontsize=6, loc='upper right')

        self.fig.autofmt_xdate(rotation=20, ha='right')
        self.canvas.draw()

    def _consultar_sunat(self):
        """Consulta razón social en SUNAT via apiperu.dev."""
        ruc = self.ruc_var.get().strip()
        if len(ruc) != 11 or not ruc.isdigit():
            messagebox.showwarning("RUC inválido",
                "El RUC debe tener exactamente 11 dígitos.", parent=self)
            return
        self.lbl_razon.config(text="Consultando SUNAT...", fg=YELLOW)
        self.update_idletasks()
        import threading
        def consultar():
            razon, estado = None, None
            apis = [
                f"https://apiperu.dev/api/ruc/{ruc}",
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
            ]
            for url in apis:
                try:
                    import urllib.request, json
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Metromecanica-Lab/1.0',
                        'Accept': 'application/json'})
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = json.loads(resp.read().decode())
                    d = data.get('data', data)
                    razon  = (d.get('razon_social') or d.get('razonSocial')
                              or d.get('nombre') or '—')
                    estado = d.get('estado') or d.get('condicion') or ''
                    if razon and razon != '—':
                        break
                except:
                    continue
            def actualizar(r, e):
                if r:
                    txt = f"{r}  [{e}]" if e else r
                    col = GREEN if 'ACTIVO' in (e or '').upper() else YELLOW
                else:
                    txt = "Sin conexión — ingresa razón social manualmente"
                    col = TXT_DIM
                self.lbl_razon.config(text=txt, fg=col)
            self.after(0, actualizar, razon, estado)
        threading.Thread(target=consultar, daemon=True).start()

    def _guardar_config(self):
        guardar_config({
            "cert_hobo":   self.cert_hobo_var.get(),
            "venc_hobo":   self.venc_hobo_var.get(),
            "cert_yowexa": self.cert_yowexa_var.get(),
            "venc_yowexa": self.venc_yowexa_var.get(),
            "presion":     self.presion_var.get(),
            "operador":    self.operador_var.get(),
        })

    def get_cond_amb(self):
        self._guardar_config()
        return {
            'inicio':       self.cond_inicio,
            'fin':          self.cond_fin,
            'cert_hobo':    self.cert_hobo_var.get(),
            'venc_hobo':    self.venc_hobo_var.get(),
            'cert_yowexa':  self.cert_yowexa_var.get(),
            'venc_yowexa':  self.venc_yowexa_var.get(),
        }

    def get_presion(self):
        try: return float(self.presion_var.get().replace(",","."))
        except: return 1014.3

    def _generar_registro(self):
        if self.df_hobo is None:
            messagebox.showwarning("Sin datos", "Carga el CSV del HOBO primero.")
            return
        if not self.operador_var.get().strip():
            messagebox.showwarning("Datos incompletos", "Ingresa el operador.")
            return
        if not self.cond_inicio:
            messagebox.showwarning("Sin condición INICIO",
                "Registra la condición INICIO antes de generar el PDF.")
            return
        if not self.cond_fin:
            messagebox.showerror(
                "⛔  Condiciones ambientales FINALES requeridas",
                "No se puede generar el PDF.\n\n"
                "Debes registrar las condiciones ambientales FINALES\n"
                "antes de generar el informe.\n\n"
                "→ Presiona  📍 Registrar FIN  en el panel de condiciones.")
            return
        fecha   = datetime.now().strftime('%Y%m%d_%H%M%S')
        ot      = self.ot_var.get().replace('/','-') or 'SIN-OT'
        import pathlib
        pathlib.Path(CARPETA_MENSUAL).mkdir(parents=True, exist_ok=True)
        ruta    = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF","*.pdf")],
            initialdir=CARPETA_MENSUAL,
            initialfile=f"RCA_{ot}_{fecha}.pdf")
        if not ruta: return

        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer, HRFlowable, Image)
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        import tempfile

        doc = SimpleDocTemplate(ruta, pagesize=A4,
                                topMargin=1.2*cm, bottomMargin=2*cm,
                                leftMargin=2*cm, rightMargin=2*cm)
        story = []
        st_sec  = ParagraphStyle('sec',  fontSize=9,  fontName='Helvetica-Bold',
                                 textColor=colors.HexColor('#1a3a6b'),
                                 spaceBefore=8, spaceAfter=4)
        st_pie  = ParagraphStyle('pie',  fontSize=7,  fontName='Helvetica',
                                 textColor=colors.grey, alignment=TA_CENTER)
        st_nota = ParagraphStyle('nota', fontSize=7.5, fontName='Helvetica-Oblique',
                                 textColor=colors.HexColor('#555555'))
        ok_c  = colors.HexColor('#d4edda')
        nok_c = colors.HexColor('#f8d7da')
        ref_c = colors.HexColor('#fff3cd')

        _encabezado_pdf(story,
                        "REGISTRO DE CONDICIONES AMBIENTALES",
                        f"OT: {self.ot_var.get() or '—'}  |  "
                        f"Operador: {self.operador_var.get()}  |  "
                        f"OIML R111 M2  |  ISO/IEC 17025",
                        "RCA-001", "1.0")

        # ── 1. Datos de calibración ──────────────────────────
        story.append(Paragraph("1. DATOS DE LA CALIBRACION", st_sec))
        gen_data = [
            ["OT / Referencia:", self.ot_var.get() or '—',
             "Operador:", self.operador_var.get()],
            ["Fecha inicio:", datetime.now().strftime('%d/%m/%Y %H:%M'),
             "Equipo patron:", "HOBO UX100-011A"],
            ["Instrumento calibrado:", self.instrumento_var.get() or '—',
             "S/N HOBO:", "21065652"],
            ["Ubicacion laboratorio:", "Lima, Peru — ~154 msnm",
             "Certificado HOBO:", self.cert_hobo_var.get()],
        ]
        gen_t = Table(gen_data, colWidths=[4*cm, 5.5*cm, 3.5*cm, 4*cm])
        gen_t.setStyle(TableStyle([
            ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('FONTNAME',   (0,0), (0,-1),  'Helvetica-Bold'),
            ('FONTNAME',   (2,0), (2,-1),  'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (0,-1),  colors.HexColor('#f0f4ff')),
            ('BACKGROUND', (2,0), (2,-1),  colors.HexColor('#f0f4ff')),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(gen_t)
        story.append(Spacer(1, 0.2*cm))

        # ── 2. Tabla inicio / fin ────────────────────────────
        story.append(Paragraph("2. CONDICIONES AMBIENTALES INICIO / FIN", st_sec))
        ci = self.cond_inicio; cf = self.cond_fin
        presion = self.get_presion()

        # Extraer correcciones si existen
        ci_corr = ci.get('corr', {}) if ci else {}
        cf_corr = cf.get('corr', {}) if cf else {}

        def fmt_corr(bruto, corregido, corr):
            if abs(corr) > 0.0001:
                return fdc(bruto,3) + "\n→ corr: " + fdc(corregido,3)
            return fdc(bruto, 3)

        tab_if = [
            ["Condiciones Ambientales", "INICIO", "FIN", "Limite OIML R111 M2", "Conforme"],
            ["Temperatura (°C)",
             fmt_corr(ci.get('temp',0), ci_corr.get('t_corr',ci.get('temp',0)),
                      ci_corr.get('corr_t',0)) if ci else '—',
             fmt_corr(cf.get('temp',0), cf_corr.get('t_corr',cf.get('temp',0)),
                      cf_corr.get('corr_t',0)) if cf else '—',
             f"{str(TEMP_MIN).replace(chr(46),chr(44))} – {str(TEMP_MAX).replace(chr(46),chr(44))} °C",
             _check(ci_corr.get('t_corr', ci.get('temp')),
                    cf_corr.get('t_corr', cf.get('temp')), TEMP_MIN, TEMP_MAX)],
            ["Humedad Relativa (%)",
             fmt_corr(ci.get('hr',0), ci_corr.get('h_corr',ci.get('hr',0)),
                      ci_corr.get('corr_h',0)) if ci else '—',
             fmt_corr(cf.get('hr',0), cf_corr.get('h_corr',cf.get('hr',0)),
                      cf_corr.get('corr_h',0)) if cf else '—',
             f"< {str(HR_MAX).replace(chr(46),chr(44))}% (no condensacion)",
             _check_max(ci_corr.get('h_corr', ci.get('hr')),
                        cf_corr.get('h_corr', cf.get('hr')), HR_MAX)],
            ["Presion Atm. (mbar)",
             fmt_corr(ci.get('presion',presion), ci_corr.get('p_corr',presion),
                      ci_corr.get('corr_p',0)) if ci else str(presion).replace('.',','),
             fmt_corr(cf.get('presion',presion), cf_corr.get('p_corr',presion),
                      cf_corr.get('corr_p',0)) if cf else str(presion).replace('.',','),
             "CIPM-2007 (empuje del aire)", "✓"],
            ["Densidad aire (kg/m3)",
             f"{str(ci_corr.get('rho_corr','—')).replace('.',',')}" if ci_corr else '—',
             f"{str(cf_corr.get('rho_corr','—')).replace('.',',')}" if cf_corr else '—',
             "Calc. CIPM-2007 c/valores corr.", "✓"],
            ["Hora de registro",
             ci.get('hora','—'), cf.get('hora','—'), "—", "—"],
        ]
        tab_if_t = Table(tab_if, colWidths=[4.5*cm, 2.5*cm, 2.5*cm, 5.5*cm, 2*cm])
        tab_if_s = TableStyle([
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
            ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
            ('FONTNAME',   (0,1), (0,-1),  'Helvetica-Bold'),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
            ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ])
        for i in range(1, len(tab_if)):
            c_row = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
            tab_if_s.add('BACKGROUND', (0,i), (-1,i), c_row)
            if tab_if[i][4] == '✓':
                tab_if_s.add('BACKGROUND', (4,i), (4,i), ok_c)
            elif tab_if[i][4] == '✗':
                tab_if_s.add('BACKGROUND', (4,i), (4,i), nok_c)
        tab_if_t.setStyle(tab_if_s)
        story.append(tab_if_t)
        story.append(Spacer(1, 0.15*cm))

        # ── 3. Tabla OIML completa ───────────────────────────
        story.append(Paragraph("3. PARAMETROS OIML R111 M2 — LECTURA ACTUAL", st_sec))

        u = self.df_hobo.iloc[-1]
        df_1h  = self.df_hobo[self.df_hobo['timestamp'] >= u['timestamp'] - pd.Timedelta(hours=1)]
        df_12h = self.df_hobo[self.df_hobo['timestamp'] >= u['timestamp'] - pd.Timedelta(hours=12)]
        v1h    = df_1h['temp_c'].max()  - df_1h['temp_c'].min()  if len(df_1h)>=2  else 0
        v12h   = df_12h['temp_c'].max() - df_12h['temp_c'].min() if len(df_12h)>=2 else 0
        rho    = calcular_densidad_aire(float(u['temp_c']), float(u['hr_pct']), ci.get('presion', presion) if ci else presion)

        t_ok   = TEMP_MIN <= float(u['temp_c']) <= TEMP_MAX
        hr_ok  = float(u['hr_pct']) <= HR_MAX
        v1_ok  = v1h  <= VAR_MAX_1H
        v12_ok = v12h <= VAR_MAX_12H

        oiml_data = [
            ["Parametro", "Valor medido", "Limite OIML R111 M2", "Estado", "Norma ref."],
            ["Temperatura",
             fdc(float(u['temp_c']), 2) + ' °C',
             f"{str(TEMP_MIN).replace(chr(46),chr(44))}–{str(TEMP_MAX).replace(chr(46),chr(44))} °C",
             "CONFORME" if t_ok else "NO CONFORME",
             "OIML R111 §B.4.2"],
            ["Humedad Relativa",
             fdc(float(u['hr_pct']), 1) + ' %',
             f"< {str(HR_MAX).replace(chr(46),chr(44))}% (no condensacion)",
             "CONFORME" if hr_ok else "NO CONFORME",
             "OIML R111 §B.4.2"],
            ["Variacion Temp. 1h",
             fdc(v1h, 2) + ' °C',
             f"<= +/-{str(VAR_MAX_1H).replace(chr(46),chr(44))} °C/h",
             "CONFORME" if v1_ok else "NO CONFORME",
             "OIML R111 §B.4.2"],
            ["Variacion Temp. 12h",
             fdc(v12h, 2) + ' °C',
             f"<= +/-{str(VAR_MAX_12H).replace(chr(46),chr(44))} °C",
             "CONFORME" if v12_ok else "NO CONFORME",
             "OIML R111 §B.4.2"],
            ["Presion atmosferica",
             str(presion).replace('.', ',') + ' mbar',
             "CIPM-2007 (empuje del aire)",
             "REFERENCIA", "CIPM-2007"],
            ["Densidad del aire",
             str(rho).replace('.', ',') + ' kg/m3' if rho else '—' if rho else "—",
             "~1,1839 kg/m3 (20°C/50%/1013 mbar)",
             "CALCULADA", "CIPM-2007"],
            ["Ultimo registro HOBO",
             str(u['timestamp'])[:16],
             f"Total registros: {len(self.df_hobo)}",
             "—", "ISO 17025 §7.5"],
        ]
        oiml_t = Table(oiml_data, colWidths=[3.8*cm, 2.8*cm, 5.2*cm, 2.8*cm, 2.4*cm])
        oiml_s = TableStyle([
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 7.5),
            ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
            ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
            ('FONTNAME',   (0,1), (0,-1),  'Helvetica-Bold'),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
            ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ])
        for i, row in enumerate(oiml_data[1:], start=1):
            c_row = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
            oiml_s.add('BACKGROUND', (0,i), (-1,i), c_row)
            if row[3] == "CONFORME":
                oiml_s.add('BACKGROUND', (3,i), (3,i), ok_c)
                oiml_s.add('FONTNAME',   (3,i), (3,i), 'Helvetica-Bold')
            elif row[3] == "NO CONFORME":
                oiml_s.add('BACKGROUND', (3,i), (3,i), nok_c)
                oiml_s.add('FONTNAME',   (3,i), (3,i), 'Helvetica-Bold')
                oiml_s.add('FONTCOLOR',  (3,i), (3,i), colors.HexColor('#c0392b'))
            elif row[3] in ("REFERENCIA","CALCULADA"):
                oiml_s.add('BACKGROUND', (3,i), (3,i), ref_c)
        oiml_t.setStyle(oiml_s)
        story.append(oiml_t)
        story.append(Spacer(1, 0.2*cm))

        # ── 4. Trazabilidad presion ──────────────────────────
        story.append(Paragraph("4. TRAZABILIDAD DE LA PRESION ATMOSFERICA", st_sec))
        pres_data = [
            ["Equipo de medicion:", "Yowexa YEM-70AL",
             "S/N:", "23111620018"],
            ["Exactitud declarada:", "U = 5 mbar, k=2 | Incert. expandida (1 hPa = 1 mbar)",
             "Calibracion:", self.cert_yowexa_var.get()],
            ["Valor registrado:", str(presion).replace('.', ',') + ' mbar',
             "Vencimiento cert.:", self.venc_yowexa_var.get() or '—'],
            ["Hora de lectura:", ci.get('hora', datetime.now().strftime('%H:%M')),
             "Operador que leyo:", self.operador_var.get()],
            ["Metodo de ingreso:", "Manual — lectura directa de pantalla", "", ""],
        ]
        pres_t = Table(pres_data, colWidths=[4*cm, 5.5*cm, 3*cm, 4.5*cm])
        pres_t.setStyle(TableStyle([
            ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('FONTNAME',   (0,0), (0,-1),  'Helvetica-Bold'),
            ('FONTNAME',   (2,0), (2,-1),  'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (0,-1),  colors.HexColor('#f0f4ff')),
            ('BACKGROUND', (2,0), (2,-1),  colors.HexColor('#f0f4ff')),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#cccccc')),
            ('SPAN',       (1,4), (3,4)),
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#fafafa')]),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(pres_t)
        story.append(Spacer(1, 0.1*cm))
        story.append(Paragraph(
            "Nota: Para clase M2 la variacion de presion en Lima (~154 msnm) es < 2 hPa/dia, "
            "representando una variacion de densidad del aire < 0.002 kg/m3, despreciable para "
            "la incertidumbre de calibracion de pesas M2 segun OIML R111.", st_nota))
        story.append(Spacer(1, 0.2*cm))

        # ── 5. Grafica HOBO ──────────────────────────────────
        story.append(Paragraph("5. GRAFICA CONDICIONES AMBIENTALES (HOBO)", st_sec))
        tmp_img = tempfile.mktemp(suffix='.png')
        _grafica_hobo_pdf(self.df_hobo, tmp_img)
        if os.path.exists(tmp_img):
            story.append(Image(tmp_img, width=17*cm, height=6*cm))
        story.append(Spacer(1, 0.2*cm))

        # ── 5.5 Correcciones por trazabilidad ───────────────────
        story.append(Paragraph("5. CORRECCIONES POR TRAZABILIDAD", st_sec))
        story.append(Paragraph(
            "Valores corregidos aplicando interpolacion lineal sobre los puntos del "
            "certificado de calibracion de cada equipo.", st_nota))
        story.append(Spacer(1, 0.15*cm))

        ci_c = ci.get('corr', {}) if ci else {}
        cf_c = cf.get('corr', {}) if cf else {}

        def fv(d, key, fmt_str=".3f"):
            v = d.get(key)
            if isinstance(v, (int, float)):
                return format(v, fmt_str).replace(".", ",")
            return '—'

        def fc(val, fmt_str=".4f", signo=False):
            """Formatea con coma decimal, signo opcional."""
            if isinstance(val, (int, float)):
                s = f"{val:{'+' if signo else ''}{fmt_str}}"
                return s.replace(".", ",")
            return '0,0000'

        corr_hdr = ["Parametro", "Lectura bruta", "Correccion", "Valor corregido", "U (k=2)"]
        corr_data_rows = []
        if ci_c:
            corr_data_rows += [
                ["T inicio (°C)",
                 fv(ci_c,"t_bruta",".4f"),
                 fc(ci_c.get("corr_t",0),".4f",True),
                 fv(ci_c,"t_corr",".4f"),
                 f"±{str(ci_c.get('u_temp',0.21)).replace('.',',')} °C"],
                ["HR inicio (%)",
                 fv(ci_c,"h_bruta",".2f"),
                 fc(ci_c.get("corr_h",0),".2f",True),
                 fv(ci_c,"h_corr",".2f"),
                 f"±{str(ci_c.get('u_hr',2.5)).replace('.',',')} %"],
                ["P inicio (mbar)",
                 fv(ci_c,"p_bruta",".2f"),
                 fc(ci_c.get("corr_p",0),".2f",True),
                 fv(ci_c,"p_corr",".2f"),
                 f"±{str(ci_c.get('u_presion',1.0)).replace('.',',')} mbar"],
                ["rho inicio (kg/m3)",
                 fv(ci_c,"rho_bruta",".5f"),
                 "—",
                 fv(ci_c,"rho_corr",".5f"),
                 "CIPM-2007"],
            ]
        if cf_c:
            corr_data_rows += [
                ["T fin (°C)",
                 fv(cf_c,"t_bruta",".4f"),
                 fc(cf_c.get("corr_t",0),".4f",True),
                 fv(cf_c,"t_corr",".4f"),
                 f"±{str(cf_c.get('u_temp',0.21)).replace('.',',')} °C"],
                ["HR fin (%)",
                 fv(cf_c,"h_bruta",".2f"),
                 fc(cf_c.get("corr_h",0),".2f",True),
                 fv(cf_c,"h_corr",".2f"),
                 f"±{str(cf_c.get('u_hr',2.5)).replace('.',',')} %"],
                ["P fin (mbar)",
                 fv(cf_c,"p_bruta",".2f"),
                 fc(cf_c.get("corr_p",0),".2f",True),
                 fv(cf_c,"p_corr",".2f"),
                 f"±{str(cf_c.get('u_presion',1.0)).replace('.',',')} mbar"],
                ["rho fin (kg/m3)",
                 fv(cf_c,"rho_bruta",".5f"),
                 "—",
                 fv(cf_c,"rho_corr",".5f"),
                 "CIPM-2007"],
            ]

        if corr_data_rows:
            corr_table_data = [corr_hdr] + corr_data_rows
            corr_t = Table(corr_table_data, colWidths=[3.8*cm,3*cm,2.5*cm,3.5*cm,3.2*cm])
            corr_s = TableStyle([
                ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',   (0,0), (-1,-1), 7.5),
                ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
                ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
                ('FONTNAME',   (0,1), (0,-1),  'Helvetica-Bold'),
                ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
                ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ])
            for i in range(1, len(corr_table_data)):
                c_row = colors.white if i % 2 == 1 else colors.HexColor('#f5f5f5')
                # Resaltar filas de densidad
                if 'rho' in corr_table_data[i][0]:
                    c_row = colors.HexColor('#e8f4ff')
                corr_s.add('BACKGROUND', (0,i), (-1,i), c_row)
                # Columna valor corregido en verde si hay corrección
                corr_s.add('FONTNAME', (3,i), (3,i), 'Helvetica-Bold')
            corr_t.setStyle(corr_s)
            story.append(corr_t)
        else:
            story.append(Paragraph(
                "No se registraron condiciones de inicio/fin o no hay correcciones configuradas.",
                st_nota))
        story.append(Spacer(1, 0.2*cm))

        # ── 6. Trazabilidad equipos ──────────────────────────
        story.append(Paragraph("6. TRAZABILIDAD DE EQUIPOS DE MEDICION", st_sec))
        tr_data = [
            ["Equipo", "Modelo", "S/N", "N° Certificado", "Lab. calibrante", "Vencimiento"],
            ["Termohigrometro", "HOBO UX100-011A", "21065652",
             self.cert_hobo_var.get(), "Elicrom",
             self.venc_hobo_var.get() or '—'],
            ["Barometro", "Yowexa YEM-70AL", "23111620018",
             self.cert_yowexa_var.get(), "—",
             self.venc_yowexa_var.get() or '—'],
        ]
        tr_t = Table(tr_data, colWidths=[3.2*cm, 3.5*cm, 2.5*cm, 2.8*cm, 2.5*cm, 2.5*cm])
        tr_t.setStyle(TableStyle([
            ('FONTNAME',   (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 7.5),
            ('BACKGROUND', (0,0), (-1,0),  colors.HexColor('#1a3a6b')),
            ('FONTCOLOR',  (0,0), (-1,0),  colors.white),
            ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#aaaaaa')),
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND', (0,1), (-1,1),  colors.white),
            ('BACKGROUND', (0,2), (-1,2),  colors.HexColor('#f5f5f5')),
        ]))
        story.append(tr_t)
        story.append(Spacer(1, 0.2*cm))

        # ── 7. Conclusion ────────────────────────────────────
        story.append(Paragraph("7. CONCLUSION", st_sec))
        todas_ok = t_ok and hr_ok and v1_ok and v12_ok
        concl_txt = (
            "Calibracion realizada dentro de los estandares de condiciones ambientales establecidos por OIML R111 / NMP 004:2007 para pesas clase M2."
            if todas_ok else
            "Condiciones ambientales fuera de los limites establecidos. Revisar impacto en la incertidumbre de medicion segun OIML R111 / NMP 004:2007.")
        concl_data = [[Paragraph(
            f"<b>{concl_txt}</b>",
            ParagraphStyle('c', fontSize=9, fontName='Helvetica-Bold',
                           textColor=colors.HexColor('#155724') if todas_ok
                           else colors.HexColor('#721c24'),
                           alignment=TA_CENTER))]]
        concl_t = Table(concl_data, colWidths=[17*cm])
        concl_t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), ok_c if todas_ok else nok_c),
            ('TOPPADDING',    (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('BOX', (0,0), (-1,-1), 0.8,
             colors.HexColor('#155724') if todas_ok else colors.HexColor('#721c24')),
        ]))
        story.append(concl_t)
        story.append(Spacer(1, 0.3*cm))

        # ── 8. Firmas ────────────────────────────────────────
        story.append(Paragraph("8. FIRMAS Y APROBACION", st_sec))
        f_data = [
            ["Elaborado por:", "", "Revisado por:", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            [f"Operador: {self.operador_var.get()}",
             f"Fecha: {datetime.now().strftime('%d/%m/%Y')}",
             "Resp. tecnico: _________________",
             "Fecha: ___________"],
        ]
        f_t = Table(f_data, colWidths=[5*cm, 3.5*cm, 5.5*cm, 3*cm])
        f_t.setStyle(TableStyle([
            ('FONTNAME',  (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE',  (0,0), (-1,-1), 8),
            ('FONTNAME',  (0,0), (0,0),   'Helvetica-Bold'),
            ('FONTNAME',  (2,0), (2,0),   'Helvetica-Bold'),
            ('LINEABOVE', (0,2), (1,2), 0.5, colors.black),
            ('LINEABOVE', (2,2), (3,2), 0.5, colors.black),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(f_t)
        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.1*cm))
        story.append(Paragraph(
            f"METROMECANICA — Laboratorio de Calibracion | Lima, Peru | "
            f"RCA-001 v1.0 | Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | "
            f"Sistema Multi-Balanza v5.0",
            st_pie))
        doc.build(story)
        self._guardar_config()
        messagebox.showinfo("PDF generado", f"Registro guardado:\n{ruta}")
        try: os.startfile(ruta)
        except: pass

    def _generar_informe_mensual(self):
        if self.df_hobo is None:
            resp = messagebox.askyesno(
                "Cargar CSV del HOBO",
                "Para el Informe Mensual necesitas cargar el CSV del HOBO.\n\n"
                "Pasos:\n"
                "1. Conecta el HOBO UX100-011A por USB\n"
                "2. Abre HOBOware → Dispositivo → Lectura\n"
                "3. HOBOware exporta el CSV automaticamente\n"
                "4. Presiona Aceptar para seleccionar el archivo\n\n"
                "¿Cargar CSV ahora?")
            if resp:
                self._cargar_csv_manual()
            if self.df_hobo is None:
                return
        mes_str = datetime.now().strftime('%B %Y').capitalize()
        operador = self.operador_var.get() or "—"
        presion  = self.get_presion()
        fecha    = datetime.now().strftime('%Y%m%d_%H%M%S')
        # Crear carpeta mensual si no existe
        import pathlib
        pathlib.Path(CARPETA_MENSUAL).mkdir(parents=True, exist_ok=True)
        ruta_def = os.path.join(CARPETA_MENSUAL,
                                f"IMA_{datetime.now().strftime('%Y%m')}_{fecha}.pdf")
        ruta = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF","*.pdf")],
            initialdir=CARPETA_MENSUAL,
            initialfile=f"IMA_{datetime.now().strftime('%Y%m')}_{fecha}.pdf")
        if not ruta: return
        if generar_informe_mensual(self.df_hobo, mes_str, operador, presion, ruta):
            messagebox.showinfo("✓ Informe generado", f"Guardado:\n{ruta}")
            try: os.startfile(ruta)
            except: pass
        else:
            messagebox.showerror("Error", "No se pudo generar el informe.")

    def _exportar_grafica(self):
        if self.df_hobo is None:
            messagebox.showwarning("Sin datos", "Carga el CSV primero.")
            return
        ruta = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG","*.png")],
            initialfile=f"ambiente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        if ruta:
            self.fig.savefig(ruta, dpi=150, bbox_inches='tight',
                             facecolor=self.fig.get_facecolor())
            messagebox.showinfo("✓ Guardado", f"Gráfica guardada:\n{ruta}")

    def on_csv_nuevo(self, filepath):
        self.after(500, lambda: self._procesar_csv(filepath))


class _HOBOWatcher(FileSystemEventHandler):
    def __init__(self, panel):
        self.panel = panel
    def on_created(self, event):
        if event.src_path.endswith('.csv'):
            time.sleep(1); self.panel.on_csv_nuevo(event.src_path)
    def on_modified(self, event):
        if event.src_path.endswith('.csv'):
            time.sleep(1); self.panel.on_csv_nuevo(event.src_path)


# ════════════════════════════════════════════════════════════
#  VENTANA PATRONES
# ════════════════════════════════════════════════════════════
class VentanaPatrones(tk.Toplevel):
    def __init__(self, parent, patrones, callback):
        super().__init__(parent)
        self.title("Gestión de Pesas Patrón")
        self.geometry("980x500"); self.configure(bg=BG)
        self.patrones = [p.copy() for p in patrones]
        self.callback = callback
        self._build(); self._cargar_tabla(); self.grab_set()

    def _build(self):
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")
        hdr = tk.Frame(self, bg=BG, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PESAS PATRON — TRAZABILIDAD",
                 bg=BG, fg=ACCENT, font=FN_TITLE).pack(side="left")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        cols = ("ID","Nominal (g)","delta_mcr (g)","U patrón (g)","Lab. calibrante","N° Certificado","Vencimiento","Estado")
        self.tabla = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for col, w in zip(cols,[90,80,85,90,110,130,100,110]):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=w, anchor="center")
        self.tabla.pack(fill="both", expand=True, padx=12, pady=8)
        self.tabla.bind("<Double-1>", self._editar)
        btns = tk.Frame(self, bg=BG, padx=12, pady=8)
        btns.pack(fill="x")
        for txt, cmd, color in [("+ Agregar", self._agregar, ACCENT2),
                                 ("Editar",   self._editar,  "#374151"),
                                 ("Eliminar", self._eliminar,"#7f1d1d")]:
            tk.Button(btns, text=txt, bg=color, fg="white",
                      font=FN_UI, relief="flat", padx=10, pady=4,
                      command=cmd).pack(side="left", padx=(0,6))
        tk.Button(btns, text="📋 Tabla EMP NMP 004:2007",
                  bg=YELLOW, fg="#1a1a1a", font=("Georgia",8,"bold"),
                  relief="flat", padx=8, pady=4,
                  command=self._ver_tabla_emp).pack(side="left", padx=(0,6))
        tk.Button(btns, text="🔬 Caracterizacion PC-008",
                  bg="#7c3aed", fg="white", font=("Georgia",8,"bold"),
                  relief="flat", padx=8, pady=4,
                  command=self._abrir_caract).pack(side="left", padx=(0,6))
        tk.Button(btns, text="Guardar y cerrar",
                  bg=GREEN, fg="white", font=("Georgia",9,"bold"),
                  relief="flat", padx=14, pady=4,
                  command=self._guardar).pack(side="right")

    def _cargar_tabla(self):
        for i in self.tabla.get_children(): self.tabla.delete(i)
        for p in self.patrones:
            est, color, dias = estado_vigencia(p["vencimiento"])
            tag = f"c{color[1:]}"
            self.tabla.insert("","end", tags=(tag,), values=(
                p["id"], fmt(p["nominal"]),
                fmt(p["dcr"], signo=True),
                fmt(p.get("u_patron", 0.060), 4),
                p.get("lab_patron","—"),
                p["n_cert"], p["vencimiento"],
                f"{est} ({dias}d)" if dias >= 0 else est))
            self.tabla.tag_configure(tag, foreground=color)

    def _form_patron(self, p=None):
        win = tk.Toplevel(self); win.title("Patrón")
        win.geometry("440x380"); win.configure(bg=PANEL); win.grab_set()
        anio = str(date.today().replace(year=date.today().year+1))
        campos = [
            ("ID:",                         "id",          p["id"]                        if p else ""),
            ("Nominal (g):",                "nominal",     str(p["nominal"])              if p else "1000"),
            ("delta_mcr (g):",              "dcr",         str(p["dcr"])                  if p else "0.0000"),
            ("U expandida k=2 (g):",        "u_patron",    str(p.get("u_patron",0.060))   if p else "0.0600"),
            ("Laboratorio calibrante:",     "lab_patron",  p.get("lab_patron","—")        if p else ""),
            ("N° Certificado:",             "n_cert",      p["n_cert"]                    if p else ""),
            ("Vencimiento (YYYY-MM-DD):",   "vencimiento", p["vencimiento"]               if p else anio),
        ]
        entries = {}
        for i,(lbl,key,val) in enumerate(campos):
            tk.Label(win, text=lbl, bg=PANEL, fg=TXT, font=FN_UI).grid(
                row=i, column=0, sticky="w", padx=14, pady=7)
            var_p = tk.StringVar(value=str(val).replace('.',',') if key in ['nominal','dcr','u_patron'] else str(val))
            if key in ['nominal', 'dcr', 'u_patron']:
                e = _entry_coma(win, var_p, font=FN_MONO, bg=PANEL2, fg=TXT,
                               insertbackground=ACCENT, relief="flat", bd=4, width=22)
            else:
                e = tk.Entry(win, textvariable=var_p, font=FN_MONO, bg=PANEL2, fg=TXT,
                             insertbackground=ACCENT, relief="flat", bd=4, width=22)
            e.grid(row=i, column=1, padx=8, pady=7)
            entries[key] = var_p
        result = [None]
        def ok():
            try:
                result[0] = {
                    "id":          entries["id"].get().strip(),
                    "nominal":     float(entries["nominal"].get().replace(",",".")),
                    "dcr":         float(entries["dcr"].get().replace(",",".")),
                    "u_patron":    float(entries["u_patron"].get().replace(",",".")),
                    "lab_patron":  entries["lab_patron"].get().strip(),
                    "n_cert":      entries["n_cert"].get().strip(),
                    "vencimiento": entries["vencimiento"].get().strip()}
                win.destroy()
            except: messagebox.showerror("Error", "Revisa los valores.", parent=win)
        tk.Button(win, text="Aceptar", bg=ACCENT2, fg="white",
                  font=FN_UI, relief="flat", padx=12, command=ok).grid(
                      row=len(campos), column=1, sticky="e", padx=8, pady=12)
        win.wait_window(); return result[0]

    def _agregar(self):
        n = self._form_patron()
        if n: self.patrones.append(n); self._cargar_tabla()

    def _editar(self, event=None):
        sel = self.tabla.selection()
        if not sel: return
        idx = self.tabla.index(sel[0])
        ed  = self._form_patron(self.patrones[idx])
        if ed: self.patrones[idx] = ed; self._cargar_tabla()

    def _eliminar(self):
        sel = self.tabla.selection()
        if not sel: return
        idx = self.tabla.index(sel[0])
        if messagebox.askyesno("Eliminar", f"¿Eliminar {self.patrones[idx]['id']}?", parent=self):
            self.patrones.pop(idx); self._cargar_tabla()

    def _ver_tabla_emp(self):
        """Muestra tabla completa de EMP clase M2 según NMP 004:2007 Tabla 1."""
        win = tk.Toplevel(self)
        win.title("Tabla 1 — EMP clase M2 | NMP 004:2007 (pág. 16)")
        win.geometry("520x680"); win.configure(bg=PANEL)
        tk.Frame(win, bg=YELLOW, height=3).pack(fill="x")
        tk.Label(win,
                 text="TABLA 1 — Errores Máximos Permisibles para Pesas",
                 bg=PANEL, fg=YELLOW,
                 font=("Georgia", 10, "bold")).pack(pady=(10,2))
        tk.Label(win,
                 text="Clase M2  |  NMP 004:2007 / OIML R111  |  Valores en mg",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(pady=(0,8))
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=10)

        # Tabla con scrollbar
        frame_t = tk.Frame(win, bg=PANEL)
        frame_t.pack(fill="both", expand=True, padx=10, pady=8)

        cols = ("Valor nominal", "EMP M2 (mg)")
        tv = ttk.Treeview(frame_t, columns=cols, show="headings", height=28)
        tv.heading("Valor nominal", text="Valor nominal")
        tv.heading("EMP M2 (mg)",  text="EMP Clase M2 (±mg)")
        tv.column("Valor nominal", width=200, anchor="center")
        tv.column("EMP M2 (mg)",  width=200, anchor="center")

        # Datos completos NMP 004:2007 Tabla 1 — Clase M2
        tabla_m2 = [
            ("5 000 kg",  "800 000"), ("2 000 kg",  "300 000"),
            ("1 000 kg",  "160 000"), ("500 kg",    "80 000"),
            ("200 kg",    "30 000"),  ("100 kg",    "16 000"),
            ("50 kg",     "8 000"),   ("20 kg",     "3 000"),
            ("10 kg",     "1 600"),   ("5 kg",      "800"),
            ("2 kg",      "300"),     ("1 kg",      "160"),
            ("500 g",     "80"),      ("200 g",     "30"),
            ("100 g",     "16"),      ("50 g",      "10"),
            ("20 g",      "8,0"),     ("10 g",      "6,0"),
            ("5 g",       "5,0"),     ("2 g",       "4,0"),
            ("1 g",       "3,0"),     ("500 mg",    "2,5"),
            ("200 mg",    "2,0"),     ("100 mg",    "1,6"),
            ("50 mg",     "—"),       ("20 mg",     "—"),
            ("10 mg",     "—"),       ("5 mg",      "—"),
            ("2 mg",      "—"),       ("1 mg",      "—"),
        ]
        for i, (nom, emp) in enumerate(tabla_m2):
            tag = "par" if i % 2 == 0 else "impar"
            tv.insert("", "end", values=(nom, emp), tags=(tag,))
        tv.tag_configure("par",   background="#1a2940")
        tv.tag_configure("impar", background="#141f2e")

        sb = ttk.Scrollbar(frame_t, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)

        tk.Label(win,
                 text="Fuente: NMP 004:2007 — Tabla 1, pág. 16 de 129",
                 bg=PANEL, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(pady=(0,6))
        tk.Button(win, text="Cerrar",
                  bg=PANEL2, fg=TXT,
                  font=FN_UI, relief="flat", padx=12, pady=4,
                  command=win.destroy).pack(pady=6)

    def _guardar(self):
        guardar_patrones(self.patrones); self.callback(self.patrones); self.destroy()


    def _abrir_caract(self):
        w = tk.Toplevel(self)
        w.title("Acceso — Caracterizacion PC-008")
        w.geometry("320x165"); w.configure(bg="#0f1828")
        w.grab_set(); w.resizable(False, False)
        tk.Frame(w, bg="#7c3aed", height=3).pack(fill="x")
        tk.Label(w, text="Caracterizacion Balanza — PC-008 INACAL",
                 bg="#0f1828", fg="#7c3aed",
                 font=("Georgia", 8, "bold")).pack(pady=(10, 4))
        tk.Label(w, text="Contrasena de acceso:",
                 bg="#0f1828", fg="#cdd9e5", font=("Georgia", 8)).pack()
        vp = tk.StringVar()
        ep = tk.Entry(w, textvariable=vp, show="*", width=22,
                      font=("Courier New", 11), bg="#141f2e", fg="#7c3aed",
                      insertbackground="#7c3aed", relief="flat", bd=3)
        ep.pack(pady=6); ep.focus_set()
        lbl_e = tk.Label(w, text="", bg="#0f1828", fg=RED,
                         font=("Georgia", 7)); lbl_e.pack()
        def _ok():
            if vp.get() == _PASSWORD_CARACT:
                w.destroy(); VentanaCaracterizacion(self, self.patrones)
            else:
                lbl_e.config(text="Contrasena incorrecta")
                vp.set(""); ep.focus_set()
        ep.bind("<Return>", lambda e: _ok())
        tk.Button(w, text="Acceder", bg="#7c3aed", fg="white",
                  font=("Georgia", 8, "bold"), relief="flat",
                  padx=12, command=_ok).pack(pady=4)


class VentanaCaracterizacion(tk.Toplevel):
    COLOR    = "#7c3aed"
    BALANZAS = ["BIOBASE RS-232", "RADWAG AS WiFi/TCP", "WANT GT-30000TR"]

    def __init__(self, parent, patrones, **kw):
        super().__init__(parent, **kw)
        self.title("Caracterizacion Balanza — PC-008 INACAL §10.2")
        self.geometry("1180x760"); self.configure(bg=BG); self.grab_set()
        self._data = self._cargar(); self._build()

    def _cargar(self):
        cfg = cargar_config(); base = {}
        for b in self.BALANZAS:
            base[b] = {
                "d": (0.001 if "RADWAG" in b else 0.1 if "WANT" in b else 0.0001),
                "d1_mm": 1.0, "d2_mm": 45.0, "D_exc": 0.0, "ciclos": [],
                "u_d_mg": 0.0, "u_E_mg": 0.0, "u_bal_mg": 0.0, "u_dI_mg": 0.0,
            }
            base[b].update(cfg.get("caracterizacion", {}).get(b, {}))
        return base

    def _guardar(self):
        cfg = cargar_config(); cfg["caracterizacion"] = self._data
        guardar_config(cfg)
        messagebox.showinfo("Guardado",
            "Caracterizacion guardada.\nSe usara en el presupuesto GUM.")
        self.destroy()

    def _build(self):
        tk.Frame(self, bg=self.COLOR, height=4).pack(fill="x")
        hdr = tk.Frame(self, bg=PANEL2, padx=14, pady=8); hdr.pack(fill="x")
        tk.Label(hdr, text="CARACTERIZACION DE BALANZA — PC-008 INACAL §10.2",
                 bg=PANEL2, fg=self.COLOR,
                 font=("Georgia", 12, "bold")).pack(side="left")
        tk.Label(hdr,
                 text="  Ec.12-17  JCGM 100:2008  NMP 004:2007  Protegido",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(side="left")
        tk.Button(hdr, text="Guardar y cerrar",
                  bg=self.COLOR, fg="white",
                  font=("Georgia", 9, "bold"), relief="flat",
                  padx=14, pady=4, command=self._guardar).pack(side="right")
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=6)
        for bal in self.BALANZAS:
            tab = tk.Frame(nb, bg=BG)
            nb.add(tab, text="  " + bal + "  ")
            self._build_tab(tab, bal)

    def _build_tab(self, parent, bal):
        import math as _m
        d = self._data[bal]
        C = "#22c55e" if "BIOBASE" in bal else "#06b6d4" if "RADWAG" in bal else "#7c3aed"

        cv = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        fr = tk.Frame(cv, bg=BG)
        fr.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=fr, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def sec(p, t):
            tk.Frame(p, bg=C, height=2).pack(fill="x")
            tk.Label(p, text=t, bg=PANEL2, fg=C, font=("Georgia", 8, "bold"),
                     padx=8, pady=4).pack(fill="x")
            f = tk.Frame(p, bg=PANEL2, padx=12, pady=10); f.pack(fill="x"); return f

        def nota(p, t):
            tk.Label(p, text=t, bg=PANEL2, fg=TXT_DIM,
                     font=("Courier New", 7, "italic")).pack(anchor="w", pady=(0, 4))

        def campo(p, lbl, key, unit, dflt=0.0):
            f = tk.Frame(p, bg=PANEL2); f.pack(fill="x", pady=2)
            tk.Label(f, text=lbl, bg=PANEL2, fg=TXT,
                     font=("Courier New", 8), width=36, anchor="w").pack(side="left")
            v = tk.StringVar(value=str(d.get(key, dflt)))
            tk.Entry(f, textvariable=v, width=14,
                     font=("Courier New", 9, "bold"), bg=PANEL, fg=C,
                     insertbackground=C, relief="flat", bd=2,
                     justify="right").pack(side="left", padx=4)
            tk.Label(f, text=unit, bg=PANEL2, fg=TXT_DIM,
                     font=("Courier New", 8)).pack(side="left")
            return v

        def bub(p, lbl, col=None):
            col = col or C
            bx = tk.Frame(p, bg="#0a1525", padx=12, pady=10)
            bx.pack(side="left", fill="x", expand=True, padx=4)
            tk.Label(bx, text=lbl, bg="#0a1525", fg="#6b7280",
                     font=("Georgia", 7)).pack()
            lv = tk.Label(bx, text="—", bg="#0a1525", fg=col,
                          font=("Courier New", 18, "bold")); lv.pack()
            tk.Label(bx, text="mg", bg="#0a1525", fg="#4b5563",
                     font=("Georgia", 7, "italic")).pack()
            return lv

        cols = tk.Frame(fr, bg=BG); cols.pack(fill="x", padx=10, pady=8)
        cL = tk.Frame(cols, bg=BG); cL.pack(side="left", fill="both", expand=True, padx=(0, 8))
        cR = tk.Frame(cols, bg=BG); cR.pack(side="left", fill="both", expand=True)

        # Seccion 1: d
        s1 = sec(cL, "1.  Division de escala  d  (Ec.14 PC-008)")
        nota(s1, "Ec.14: u_d = (d/sqrt2)*sqrt2 = d   (sqrt2 por 2 lecturas: patron + pesa)")
        v_d = campo(s1, "d   division de escala", "d", "g", d.get("d", 0.001))
        lbl_ud = tk.Label(s1, text="u_d = ---", bg=PANEL2, fg=C,
                          font=("Courier New", 9, "bold"))
        lbl_ud.pack(anchor="w", pady=2)

        def _upd_d(*_):
            try:
                dv = float(v_d.get().replace(",", "."))
                d["d"] = dv; d["u_d_mg"] = dv * 1000
                lbl_ud.config(text=f"u_d = {dv} g = {dv*1000:.4f} mg   (Ec.14)")
                _recalc()
            except Exception:
                pass
        v_d.trace_add("write", _upd_d)

        # Seccion 2: excentricidad
        s2 = sec(cL, "2.  Excentricidad  u_E  (Ec.15 PC-008)")
        nota(s2, "Ec.15: u_E=(d1/d2*D)/(2*sqrt3)   D=dif.max 5 pos   d1=dist centros(mm)   d2=radio plato(mm)")
        v_D  = campo(s2, "D   diferencia maxima excentricidad", "D_exc",  "g",  d.get("D_exc", 0.0))
        v_d1 = campo(s2, "d1  distancia entre centros (mm)",   "d1_mm",  "mm", d.get("d1_mm", 1.0))
        v_d2 = campo(s2, "d2  distancia centro plato a esquina (mm)", "d2_mm", "mm", d.get("d2_mm", 45.0))
        lbl_uE = tk.Label(s2, text="u_E = ---", bg=PANEL2, fg=C,
                          font=("Courier New", 9, "bold"))
        lbl_uE.pack(anchor="w", pady=2)

        def _upd_exc(*_):
            try:
                Dv  = float(v_D.get().replace(",", "."))
                d1v = float(v_d1.get().replace(",", "."))
                d2v = float(v_d2.get().replace(",", "."))
                d["D_exc"] = Dv; d["d1_mm"] = d1v; d["d2_mm"] = d2v
                uE = (d1v / d2v * Dv) / (2 * _m.sqrt(3)) if d2v > 0 else 0.0
                d["u_E_mg"] = uE * 1000
                lbl_uE.config(
                    text=f"u_E=({d1v}/{d2v}*{Dv})/(2*sqrt3)={uE:.6f}g={uE*1000:.4f}mg  (Ec.15)")
                _recalc()
            except Exception:
                pass
        for v in [v_D, v_d1, v_d2]:
            v.trace_add("write", _upd_exc)

        # Seccion 3: 10 ciclos ABA
        s3 = sec(cR, "3.  Diez ciclos ABA  —  s(dI) agrupada  (Ec.12-13 PC-008)")
        nota(s3, "Ec.12: u(dI)=sqrt(s2(dI))   Ec.13: s2=(1/J)*sum(sj2)   dI=Ix-(Ir1+Ir2)/2")

        hdr_t = tk.Frame(s3, bg="#1a3a6b"); hdr_t.pack(fill="x")
        for ct, cw in [("Ciclo", 9), ("dI medido (g)", 18), ("dI - media", 16), ("(dI-media)^2", 18)]:
            tk.Label(hdr_t, text=ct, bg="#1a3a6b", fg="white",
                     font=("Courier New", 7, "bold"),
                     width=cw, anchor="w").pack(side="left", padx=1, pady=3)

        c_vars, c_lbls = [], []
        for i in range(10):
            val = d["ciclos"][i] if i < len(d["ciclos"]) else 0.0
            bg_r = PANEL2 if i % 2 == 0 else PANEL
            rr = tk.Frame(s3, bg=bg_r); rr.pack(fill="x")
            tk.Label(rr, text=f"  Ciclo {i+1:02d}", bg=bg_r, fg=TXT_DIM,
                     font=("Courier New", 8), width=9, anchor="w").pack(side="left", padx=1, pady=3)
            vv = tk.StringVar(value=str(val) if val != 0.0 else "")
            tk.Entry(rr, textvariable=vv, width=18,
                     font=("Courier New", 9, "bold"), bg=PANEL, fg=C,
                     insertbackground=C, relief="flat", bd=2,
                     justify="right").pack(side="left", padx=2)
            l1 = tk.Label(rr, text="---", bg=bg_r, fg=TXT_DIM,
                          font=("Courier New", 7), width=16, anchor="e")
            l1.pack(side="left", padx=1)
            l2 = tk.Label(rr, text="---", bg=bg_r, fg=TXT_DIM,
                          font=("Courier New", 7), width=18, anchor="e")
            l2.pack(side="left", padx=1)
            c_vars.append(vv); c_lbls.append((l1, l2))

        res_f = tk.Frame(s3, bg="#0a1525", padx=10, pady=8)
        res_f.pack(fill="x", pady=(6, 0))
        lbl_n   = tk.Label(res_f, text="n = 0", bg="#0a1525", fg=TXT_DIM,
                           font=("Courier New", 8)); lbl_n.pack(anchor="w")
        lbl_med = tk.Label(res_f, text="media = ---", bg="#0a1525", fg=TXT_DIM,
                           font=("Courier New", 8)); lbl_med.pack(anchor="w")
        lbl_s   = tk.Label(res_f, text="s(dI) = ---", bg="#0a1525", fg=C,
                           font=("Courier New", 10, "bold")); lbl_s.pack(anchor="w")
        lbl_udI = tk.Label(res_f, text="u(dI) = ---", bg="#0a1525", fg="#22c55e",
                           font=("Courier New", 10, "bold")); lbl_udI.pack(anchor="w")

        def _upd_ciclos(*_):
            vals = []
            for vv in c_vars:
                try: vals.append(float(vv.get().replace(",", ".")))
                except Exception: pass
            d["ciclos"] = vals; n = len(vals)
            if n >= 2:
                med = sum(vals) / n
                s2v = sum((x - med) ** 2 for x in vals) / (n - 1)
                s   = _m.sqrt(s2v)
                for vv, (l1, l2) in zip(c_vars, c_lbls):
                    try:
                        vi = float(vv.get().replace(",", "."))
                        dv2 = vi - med
                        l1.config(text=f"{dv2:+.6f}")
                        l2.config(text=f"{dv2**2:.8f}")
                    except Exception:
                        l1.config(text="---"); l2.config(text="---")
                d["u_dI_mg"] = s * 1000
                lbl_n.config(text=f"n = {n} ciclos validos")
                lbl_med.config(text=f"media dI = {med:.6f} g")
                lbl_s.config(text=f"s(dI) = {s:.6f} g = {s*1000:.4f} mg   (Ec.13)")
                lbl_udI.config(text=f"u(dI) = sqrt(s2) = {s*1000:.4f} mg   (Ec.12)")
            else:
                d["u_dI_mg"] = 0.0
                lbl_n.config(text=f"n = {n}  (minimo 2 ciclos)")
                lbl_s.config(text="s(dI) = ---")
                lbl_udI.config(text="u(dI) = ---")
            _recalc()
        for vv in c_vars:
            vv.trace_add("write", _upd_ciclos)

        # Seccion 4: resultado
        s4 = sec(fr, "4.  u(Dbalanza)  (Ec.16)  y  condicion aceptacion  (Ec.22)")
        tk.Label(s4,
                 text="Ec.16: u(Dbalanza)=sqrt(u_d^2+u_E^2)   "
                      "Ec.22: U(m_ct)=k*u_c <= (1/3)*delta_m(MPE)",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Courier New", 8)).pack(anchor="w", pady=(0, 8))

        brow = tk.Frame(s4, bg=PANEL2); brow.pack(fill="x", pady=4)
        bu_ud  = bub(brow, "u_d  resolucion")
        bu_uE  = bub(brow, "u_E  excentricidad")
        bu_ub  = bub(brow, "u(Dbalanza)  Ec.16",   col="#22c55e")
        bu_udI = bub(brow, "u(dI)  10 ciclos ABA", col="#facc15")

        lbl_res = tk.Label(s4, text="", bg=PANEL2, fg="#22c55e",
                           font=("Courier New", 9, "bold"))
        lbl_res.pack(anchor="w", pady=(6, 2))
        tk.Label(s4, text="Condicion PC-008 Ec.22:   U(m_ct) <= (1/3) * MPE",
                 bg=PANEL2, fg=YELLOW,
                 font=("Georgia", 8, "bold")).pack(anchor="w")

        def _recalc(*_):
            try:
                ud  = d.get("u_d_mg",  0) / 1000
                uE  = d.get("u_E_mg",  0) / 1000
                ub2 = _m.sqrt(ud**2 + uE**2)
                udI = d.get("u_dI_mg", 0) / 1000
                d["u_bal_mg"] = ub2 * 1000
                bu_ud.config(text=f"{ud*1000:.4f}")
                bu_uE.config(text=f"{uE*1000:.4f}")
                bu_ub.config(text=f"{ub2*1000:.4f}")
                bu_udI.config(text=f"{udI*1000:.4f}")
                lbl_res.config(
                    text=f"u(Dbalanza)=sqrt({ud*1000:.4f}^2+{uE*1000:.4f}^2)"
                         f"={ub2*1000:.4f}mg   u(dI)={udI*1000:.4f}mg")
            except Exception:
                pass

        _upd_d(); _upd_exc(); _upd_ciclos(); _recalc()


# ════════════════════════════════════════════════════════════
#  PANEL BALANZA
# ════════════════════════════════════════════════════════════
class PanelBalanza(tk.Frame):
    def __init__(self, parent, nombre, color, capacidad,
                 division, decimales, patrones_ref, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self.nombre = nombre; self.color = color
        self.decimales = decimales; self.patrones = patrones_ref
        self.ultimo_val = None; self.conectado = False
        self.paso_aba = 0; self.ir1 = self.it = self.ir2 = None
        self.on_aba_completo = None
        self._build()

    def _build(self):
        tk.Frame(self, bg=self.color, height=4).pack(fill="x")
        hdr = tk.Frame(self, bg=PANEL2, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text=self.nombre, bg=PANEL2, fg=self.color,
                 font=("Georgia", 11, "bold")).pack(side="left")
        self.lbl_estado = tk.Label(hdr, text="Desconectado",
                                   bg=PANEL2, fg=RED, font=FN_SM)
        self.lbl_estado.pack(side="right")
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        col_l = tk.Frame(body, bg=PANEL2)
        col_l.pack(side="left", fill="both", padx=(0,3), ipadx=4)
        id_f = tk.Frame(col_l, bg=PANEL2, padx=10, pady=8)
        id_f.pack(fill="x")
        tk.Label(id_f, text="ID PESA", bg=PANEL2, fg=self.color,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        self.e_desc = tk.Entry(id_f, width=20,
                               font=("Courier New",13,"bold"),
                               bg="#0d1f38", fg="#f0f0f0",
                               insertbackground=self.color,
                               relief="flat", bd=0)
        self.e_desc.pack(fill="x", pady=(3,0))
        tk.Frame(id_f, bg=self.color, height=2).pack(fill="x", pady=(3,0))
        tk.Label(id_f, text="Ingresa el codigo antes de iniciar",
                 bg=PANEL2, fg="#6b7280",
                 font=("Georgia",7,"italic")).pack(anchor="w", pady=(2,0))
        disp = tk.Frame(col_l, bg="#0a1525", padx=10, pady=14)
        disp.pack(fill="x")
        self.lbl_valor = tk.Label(disp, text="--,---- g",
                                  bg="#0a1525", fg=GREEN, font=FN_BIG)
        self.lbl_valor.pack()
        self.lbl_raw = tk.Label(disp, text="raw: --",
                                bg="#0a1525", fg=TXT_DIM, font=("Courier New",7))
        self.lbl_raw.pack()
        self.lbl_estab = tk.Label(disp, text="--",
                                  bg="#0a1525", fg=TXT_DIM, font=("Courier New",7))
        self.lbl_estab.pack()
        col_r = tk.Frame(body, bg=PANEL2)
        col_r.pack(side="left", fill="both", expand=True, padx=(3,0))
        pf = tk.Frame(col_r, bg=PANEL2, padx=10, pady=8)
        pf.pack(fill="x")
        tk.Frame(pf, bg=self.color, height=2).pack(fill="x", pady=(0,5))
        tk.Label(pf, text="PATRON DE REFERENCIA", bg=PANEL2, fg=self.color,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        row_pat = tk.Frame(pf, bg=PANEL2); row_pat.pack(fill="x", pady=(4,0))
        tk.Label(row_pat, text="Patron:", bg=PANEL2, fg=TXT,
                 font=FN_UI).pack(side="left")
        self.combo_pat = ttk.Combobox(row_pat, width=24, state="readonly")
        self.combo_pat.pack(side="left", padx=6)
        self.combo_pat.bind("<<ComboboxSelected>>", self._on_patron)
        self.lbl_pat_info = tk.Label(pf, text="Nominal: --  |  delta_mcr: --  |  Cert.: --",
                                     bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
        self.lbl_pat_info.pack(anchor="w", pady=(2,0))
        self.lbl_pat_venc = tk.Label(pf, text="Vence: --",
                                     bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
        self.lbl_pat_venc.pack(anchor="w")
        self.lbl_emp_info = tk.Label(pf, text="EMP clase M2: --",
                                     bg=PANEL2, fg=YELLOW, font=("Courier New",8,"bold"))
        self.lbl_emp_info.pack(anchor="w")
        self.actualizar_patrones()
        aba = tk.Frame(col_r, bg=PANEL2, padx=10, pady=8)
        aba.pack(fill="x")
        tk.Frame(aba, bg=self.color, height=2).pack(fill="x", pady=(0,5))
        tk.Label(aba, text="PROCEDIMIENTO ABA", bg=PANEL2, fg=self.color,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        fml = tk.Frame(aba, bg="#0a1525", padx=8, pady=5)
        fml.pack(fill="x", pady=(3,6))
        tk.Label(fml, text="delta_mct = It - (Ir1+Ir2)/2 + delta_mcr",
                 bg="#0a1525", fg=self.color,
                 font=("Courier New",9,"bold")).pack()
        self.lbl_id_ref = tk.Label(aba, text="ID: --",
                                   bg=PANEL2, fg=self.color,
                                   font=("Courier New",8,"bold"), anchor="w")
        self.lbl_id_ref.pack(fill="x")
        if hasattr(self, "e_desc"):
            self.e_desc.bind("<KeyRelease>",
                lambda e: self.lbl_id_ref.config(
                    text=f"ID: {self.e_desc.get() or '--'}"))
        self.lbl_paso = tk.Label(aba, text="Presiona Iniciar ABA",
                                 bg=PANEL2, fg=TXT_DIM,
                                 font=("Courier New",8,"bold"),
                                 wraplength=700, justify="left")
        self.lbl_paso.pack(anchor="w", pady=(4,3))
        vals_f = tk.Frame(aba, bg="#0a1525", padx=8, pady=6)
        vals_f.pack(fill="x", pady=(0,4))
        for lbl_txt, attr in [("Ir1 -- Patron A1:","lbl_ir1"),
                               ("It  -- Incognita B:","lbl_it"),
                               ("Ir2 -- Patron A2:","lbl_ir2")]:
            f2 = tk.Frame(vals_f, bg="#0a1525"); f2.pack(fill="x", pady=1)
            tk.Label(f2, text=lbl_txt, bg="#0a1525", fg=TXT_DIM,
                     font=("Courier New",8), width=22, anchor="w").pack(side="left")
            lv = tk.Label(f2, text="--", bg="#0a1525", fg=GREEN,
                          font=("Courier New",10,"bold"), anchor="e")
            lv.pack(side="left", fill="x", expand=True)
            setattr(self, attr, lv)
        self.lbl_res = tk.Label(aba, text="--",
                                bg=PANEL2, fg=GREEN,
                                font=("Courier New",9,"bold"),
                                wraplength=700, justify="left")
        self.lbl_res.pack(anchor="w", pady=(0,8))
        btns = tk.Frame(aba, bg=PANEL2); btns.pack(fill="x")
        self.btn_iniciar = tk.Button(btns, text="Iniciar ABA",
                                     bg=self.color, fg="white",
                                     font=("Georgia",9,"bold"),
                                     relief="flat", padx=16, pady=6,
                                     command=self.iniciar_aba)
        self.btn_iniciar.pack(side="left", padx=(0,8))
        self.btn_capturar = tk.Button(btns, text="Capturar lectura",
                                      bg="#166534", fg="white",
                                      font=("Georgia",9,"bold"),
                                      relief="flat", padx=16, pady=6,
                                      state="disabled", command=self.capturar)
        self.btn_capturar.pack(side="left", padx=(0,8))
        tk.Button(btns, text="Cancelar",
                  bg=PANEL, fg=TXT_DIM,
                  font=("Georgia",8), relief="flat",
                  padx=10, pady=6,
                  command=self.cancelar_aba).pack(side="left")
        lf = tk.Frame(aba, bg=PANEL2, pady=4); lf.pack(fill="x")
        self.led_cv = tk.Canvas(lf, width=16, height=16,
                                bg=PANEL2, highlightthickness=0)
        self.led_cv.pack(side="left", padx=(0,5))
        self._led_dot = self.led_cv.create_oval(1,1,15,15,
                                                fill="#1a1a1a", outline="#374151")
        self.lbl_led = tk.Label(lf, text="CICLO ABA INICIADO",
                                bg=PANEL2, fg="#374151",
                                font=("Georgia",7,"bold"))
        self.lbl_led.pack(side="left")
        self._led_on = False; self._led_blink = False
    def set_valor(self, valor, raw, estable=True):
        self.ultimo_val = valor
        self.lbl_raw.config(text=f"raw: {(raw or '—')[:45]}")
        if valor is not None:
            self.lbl_valor.config(text=f"{fmt(valor, self.decimales)} g", fg=GREEN)
            self.lbl_estab.config(
                text="ESTABLE" if estable else "inestable",
                fg=GREEN if estable else YELLOW)
        else:
            self.lbl_valor.config(text="--,---- g", fg=TXT_DIM)

    def set_conectado(self, ok, msg=""):
        self.conectado = ok
        self.lbl_estado.config(
            text=f"{'Conectado' if ok else msg or 'Desconectado'}",
            fg=GREEN if ok else RED)

    def actualizar_patrones(self):
        vals = [f"{p['id']} ({p['nominal']}g)" for p in self.patrones]
        self.combo_pat["values"] = vals
        if vals: self.combo_pat.current(0); self._on_patron()

    def _on_patron(self, event=None):
        idx = self.combo_pat.current()
        if idx < 0 or idx >= len(self.patrones): return
        p = self.patrones[idx]
        est, color, dias = estado_vigencia(p["vencimiento"])
        self.lbl_pat_info.config(
            text=f"Nominal: {fmt(p['nominal'])} g  |  delta_mcr: {fmt(p['dcr'],signo=True)} g  |  Cert.: {p['n_cert']}")
        self.lbl_pat_venc.config(
            text=f"Vence: {p['vencimiento']}  —  {est} ({abs(dias)}d)", fg=color)
        # Mostrar EMP clase M2 al seleccionar la pesa
        emp = obtener_emp_m2_directo(p["nominal"])
        if emp is not None:
            emp_str = f"{emp:.3f}".replace(".",",")
            self.lbl_emp_info.config(
                text=f"EMP clase M2: ±{emp_str} mg  (NMP 004:2007 Tabla 1)",
                fg=YELLOW)
            # Sincronizar u_patron al PanelGUM automáticamente
            try:
                app = self.winfo_toplevel()
                if hasattr(app, 'panel_gum'):
                    u_p = p.get('u_patron', 0.060)
                    app.panel_gum._params['u_patron'] = u_p
                    app.panel_gum.var_u_patron.set(str(u_p))
                    app.panel_gum._calcular()
            except Exception:
                pass

    def _patron_actual(self):
        idx = self.combo_pat.current()
        if idx < 0 or idx >= len(self.patrones): return None
        return self.patrones[idx]

    def iniciar_aba(self):
        if not self.conectado:
            messagebox.showwarning("Sin conexion", f"Conecta la {self.nombre} primero.")
            return
        if not self._patron_actual():
            messagebox.showwarning("Sin patron", "Selecciona un patron.")
            return
        self.paso_aba = 1; self.ir1 = self.it = self.ir2 = None
        self.lbl_ir1.config(text="--"); self.lbl_it.config(text="--")
        self.lbl_ir2.config(text="--"); self.lbl_res.config(text="--", fg=GREEN)
        self.btn_capturar.config(state="normal")
        self.btn_iniciar.config(state="disabled")
        self._led_blink = True; self._led_on = False
        self.lbl_led.config(text="CICLO ABA INICIADO", fg="#ef4444")
        self._tick_led()
        self._actualizar_paso()

    def _actualizar_paso(self):
        msgs = {1:"Paso 1/3 — PESA PATRON → Capturar Ir1",
                2:"Paso 2/3 — PESA INCOGNITA → Capturar It",
                3:"Paso 3/3 — PESA PATRON → Capturar Ir2"}
        self.lbl_paso.config(text=msgs.get(self.paso_aba,""), fg=self.color)

    def capturar(self):
        if self.ultimo_val is None:
            messagebox.showwarning("Sin lectura", "Espera una lectura estable.")
            return
        v = self.ultimo_val; d = self.decimales
        if   self.paso_aba == 1: self.ir1 = v; self.lbl_ir1.config(text=f"{fmt(v,d)} g"); self.paso_aba = 2
        elif self.paso_aba == 2: self.it  = v; self.lbl_it.config(text=f"{fmt(v,d)} g");  self.paso_aba = 3
        elif self.paso_aba == 3: self.ir2 = v; self.lbl_ir2.config(text=f"{fmt(v,d)} g"); self._calcular_aba(); return
        self._actualizar_paso()

    def _calcular_aba(self):
        pat = self._patron_actual()
        if not pat: return
        ir_prom = (self.ir1 + self.ir2) / 2.0
        dct     = self.it - ir_prom + pat["dcr"]
        dct_mg  = abs(dct) * 1000  # convertir a mg

        # Verificar EMP clase M2 segun NMP 004:2007
        emp_mg  = obtener_emp_m2_directo(pat["nominal"])
        conforme = dct_mg <= emp_mg if emp_mg else True
        emp_txt = f"{emp_mg:.3f} mg".replace(".",",") if emp_mg else "—"

        color_res = GREEN if conforme else RED
        estado_emp = "CONFORME" if conforme else "NO CONFORME"

        self.lbl_res.config(
            text=(f"Ir_prom = {fmt(ir_prom,self.decimales)} g\n"
                  f"delta_mct = {fmt(dct,self.decimales,True)} g  ({abs(dct)*1000:.3f} mg)\n"
                  f"EMP M2: {emp_txt}  →  {estado_emp}"),
            fg=color_res)
        self.btn_capturar.config(state="disabled")
        self.btn_iniciar.config(state="normal")
        self._led_blink = False
        self.led_cv.itemconfig(self._led_dot, fill="#22c55e", outline="#16a34a")
        self.lbl_led.config(text="ABA COMPLETADO", fg="#22c55e")
        self.lbl_paso.config(text=f"ABA completado -- {estado_emp}", fg=color_res)
        self.paso_aba = 0
        # Anuncio de voz
        hablar("Ciclo A, B, A... Completado")
        if self.on_aba_completo:
            self.on_aba_completo({
                "balanza":   self.nombre,
                "id_pesa":   self.e_desc.get().strip() or "pesa",
                "patron_id": pat["id"],
                "nominal":   pat["nominal"],
                "n_cert":    pat["n_cert"],
                "ir1":       self.ir1, "it":  self.it, "ir2": self.ir2,
                "ir_prom":   ir_prom,  "dct": dct,     "dcr": pat["dcr"],
                "decimales": self.decimales,
                "dct_mg":    round(dct_mg, 4),
                "emp_mg":    emp_mg,
                "conforme_emp": conforme,
            })

    def _auto_captura_radwag(self, val, estable):
        """Captura automática al recibir dato del RADWAG (vía Print)."""
        if self.paso_aba > 0 and estable and self.ultimo_val == val:
            self.capturar()

    def _auto_captura_biobase(self, val):
        """Captura automática al recibir dato de BIOBASE (vía Print)."""
        if self.paso_aba > 0 and self.ultimo_val == val:
            self.capturar()

    def cancelar_aba(self):
        self.paso_aba = 0
        self.btn_capturar.config(state="disabled")
        self.btn_iniciar.config(state="normal")
        self._led_blink = False
        self.led_cv.itemconfig(self._led_dot, fill="#1a1a1a", outline="#374151")
        self.lbl_led.config(text="CICLO ABA INICIADO", fg="#374151")
        self.lbl_paso.config(text="Presiona Iniciar ABA", fg=TXT_DIM)
        self.lbl_res.config(text="--")

    def _tick_led(self):
        if not self._led_blink: return
        self._led_on = not self._led_on
        self.led_cv.itemconfig(self._led_dot,
            fill="#ef4444" if self._led_on else "#7f1d1d",
            outline="#fca5a5" if self._led_on else "#450a0a")
        self.after(400, self._tick_led)


# ════════════════════════════════════════════════════════════
#  CONEXIONES
# ════════════════════════════════════════════════════════════
class ConexionBiobase:
    def __init__(self, panel):
        self.panel   = panel
        self.activo  = False
        self._ser    = None
        self._ultimo_raw = ""

    def conectar(self, port, baud):
        try:
            self._ser = serial.Serial(port, baud, timeout=1)
            self.activo = True
            self.panel.set_conectado(True)
            threading.Thread(target=self._loop, daemon=True).start()
            return True
        except Exception as e:
            messagebox.showerror("Error BIOBASE", str(e))
            return False

    def desconectar(self):
        self.activo = False
        if self._ser and self._ser.is_open:
            try: self._ser.close()
            except: pass

    def _loop(self):
        while self.activo:
            try:
                if self._ser and self._ser.in_waiting:
                    raw = self._ser.readline().decode("ascii","ignore").strip()
                    if not raw:
                        continue
                    val = parsear_serial(raw)
                    # Actualizar display
                    self.panel.after(0, self.panel.set_valor, val, raw, True)
                    # Auto-captura ABA si está esperando lectura
                    # La BIOBASE envía cuando presionas Print — capturar automáticamente
                    if (val is not None and
                            self.panel.paso_aba > 0 and
                            self.panel.btn_capturar.cget("state") == "normal"):
                        self.panel.after(100, self.panel._auto_captura_biobase, val)
                else:
                    time.sleep(0.05)
            except:
                break
        if self.activo:
            self.panel.after(0, self.panel.set_conectado, False, "Error serial")

class ConexionRadwag:
    def __init__(self, panel):
        self.panel  = panel
        self.activo = False
        self._sock  = None
        self._buffer = ""

    def conectar(self, ip, port):
        self.activo = True
        threading.Thread(target=self._loop, args=(ip, port), daemon=True).start()

    def desconectar(self):
        self.activo = False
        if self._sock:
            try: self._sock.close()
            except: pass

    def solicitar_lectura(self):
        """Envía comando SI (Send Indication) para pedir lectura actual."""
        if self._sock:
            try: self._sock.sendall(b"SI\r\n")
            except: pass

    def _loop(self, ip, port):
        while self.activo:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(3)
                self._sock.connect((ip, port))
                self.panel.after(0, self.panel.set_conectado, True)
                self._sock.settimeout(0.5)
                self._buffer = ""
                while self.activo:
                    try:
                        data = self._sock.recv(256)
                        if not data: break
                        texto = data.decode("ascii", "ignore")
                        self._buffer += texto
                        # Procesar líneas completas
                        while "\n" in self._buffer or "\r" in self._buffer:
                            for sep in ["\r\n", "\n", "\r"]:
                                if sep in self._buffer:
                                    linea, self._buffer = self._buffer.split(sep, 1)
                                    linea = linea.strip()
                                    if not linea:
                                        continue
                                    val, est = parsear_radwag(linea)
                                    if val is not None:
                                        self.panel.after(0, self.panel.set_valor,
                                                         val, linea, est)
                                        # Auto-captura si ABA está esperando
                                        if (self.panel.paso_aba > 0 and
                                                self.panel.btn_capturar.cget("state") == "normal"):
                                            self.panel.after(
                                                50, self.panel._auto_captura_radwag,
                                                val, est)
                                    break
                            else:
                                break
                    except socket.timeout:
                        continue
                    except Exception:
                        break
            except Exception:
                pass
            if self.activo:
                self.panel.after(0, self.panel.set_conectado, False, "Reconectando...")
                time.sleep(2)



# ════════════════════════════════════════════════════════════
#  PANEL INCERTIDUMBRE GUM
# ════════════════════════════════════════════════════════════
class PanelGUM(tk.Frame):
    COLOR = "#7c3aed"

    def __init__(self, parent, app_ref, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.app = app_ref
        self._params = self._cargar_params()
        self._historial = self._cargar_historial()
        self._build()
        self._calcular()

    def _cargar_params(self):
        cfg = cargar_config()
        defaults = {"n_series":5,"s_rep":0.300,"u_patron":0.060,"dcr":0.050,
                    "d_bal":1.0,"exc_max":0.200,"rho_pesa":8000,"rho_patron":8000,
                    "deriva":50.0,"nominal":20000}
        return {**defaults, **cfg.get("gum_params",{})}

    def _guardar_params(self):
        cfg = cargar_config()
        cfg["gum_params"] = self._params
        cfg["gum_historial"] = self._historial
        guardar_config(cfg)

    def _cargar_historial(self):
        return cargar_config().get("gum_historial",[
            {"fecha":"15/03/2024","dm":120,"U":180,"cert":"CERT-2024-001"},
            {"fecha":"20/10/2024","dm":155,"U":175,"cert":"CERT-2024-028"},
        ])

    def _build(self):
        tk.Frame(self, bg=self.COLOR, height=4).pack(fill="x")
        hdr = tk.Frame(self, bg=PANEL2, padx=14, pady=7)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PRESUPUESTO DE INCERTIDUMBRE — GUM",
                 bg=PANEL2, fg=self.COLOR,
                 font=("Georgia",12,"bold")).pack(side="left")
        tk.Label(hdr, text="   EURAMET cg-18 v4  ·  JCGM 100:2008  ·  PC-008 INACAL",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia",8,"italic")).pack(side="left")
        tk.Button(hdr, text="💾 Guardar parámetros",
                  bg=self.COLOR, fg="white",
                  font=("Georgia",8,"bold"),
                  relief="flat", padx=10, pady=3,
                  command=self._guardar_y_recalc).pack(side="right")
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        col_l = tk.Frame(body, bg=BG)
        col_l.pack(side="left", fill="both", expand=True, padx=(0,8))
        self._build_params(col_l)
        col_r = tk.Frame(body, bg=BG)
        col_r.pack(side="left", fill="both", expand=True)
        self._build_resultados(col_r)
        self._build_historial(col_r)

    def _sec(self, p, txt):
        tk.Frame(p, bg=self.COLOR, height=2).pack(fill="x", pady=(8,3))
        tk.Label(p, text=txt, bg=BG, fg=self.COLOR,
                 font=("Georgia",8,"bold")).pack(anchor="w")

    def _fila(self, p, label, key, unit=""):
        f = tk.Frame(p, bg=PANEL2, padx=6, pady=3); f.pack(fill="x", pady=1)
        tk.Label(f, text=label, bg=PANEL2, fg=TXT,
                 font=("Courier New",8), width=32, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(self._params.get(key,"")))
        e = tk.Entry(f, textvariable=var, width=10,
                     font=("Courier New",9,"bold"),
                     bg=PANEL, fg="#22c55e",
                     insertbackground=self.COLOR,
                     relief="flat", bd=2, justify="right")
        e.pack(side="left", padx=4)
        if unit:
            tk.Label(f, text=unit, bg=PANEL2, fg=TXT_DIM,
                     font=("Courier New",8)).pack(side="left")
        var.trace_add("write", lambda *_: self._on_change(key, var))
        setattr(self, f"var_{key}", var)

    def _build_params(self, p):
        tk.Label(p, text="PARÁMETROS DE ENTRADA", bg=BG, fg=TXT_DIM,
                 font=("Georgia",8,"bold")).pack(anchor="w", pady=(0,4))
        self._sec(p, "① Repetibilidad (Tipo A)")
        self._fila(p, "n series ABA realizadas", "n_series", unit="series")
        self._fila(p, "s — desviación estándar medida", "s_rep", unit="g")
        self._sec(p, "② Patrón de referencia (Tipo B)")
        # Campo u_patron destacado — se jalará del patrón seleccionado
        f_up = tk.Frame(p, bg="#0a1525", padx=8, pady=6); f_up.pack(fill="x", pady=2)
        tk.Label(f_up, text="U expandida patrón (k=2) — desde patrones.json",
                 bg="#0a1525", fg=self.COLOR,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        self.var_u_patron = tk.StringVar(value=str(self._params.get("u_patron",0.060)))
        e_up = tk.Entry(f_up, textvariable=self.var_u_patron, width=12,
                        font=("Courier New",13,"bold"),
                        bg="#0d1f38", fg="#f0f0f0",
                        insertbackground=self.COLOR,
                        relief="flat", bd=0, justify="right")
        e_up.pack(fill="x", pady=(2,0))
        tk.Frame(f_up, bg=self.COLOR, height=2).pack(fill="x", pady=(3,0))
        tk.Label(f_up, text="Se actualiza automáticamente al seleccionar patrón en la balanza",
                 bg="#0a1525", fg="#6b7280",
                 font=("Georgia",7,"italic")).pack(anchor="w", pady=(2,0))
        self.var_u_patron.trace_add("write",
            lambda *_: self._on_change("u_patron", self.var_u_patron))
        self._fila(p, "δmR — corrección del patrón", "dcr", unit="g")
        self._fila(p, "ρ patrón — densidad", "rho_patron", unit="kg/m³")
        self._sec(p, "③ Resolución balanza (Tipo B)")
        self._fila(p, "d — división de escala", "d_bal", unit="g")
        f_mat = tk.Frame(p, bg=PANEL2, padx=6, pady=3); f_mat.pack(fill="x", pady=1)
        tk.Label(f_mat, text="Material de la pesa", bg=PANEL2, fg=TXT,
                 font=("Courier New",8), width=32, anchor="w").pack(side="left")
        mats = [("Acero inox 316 — 8000","8000"),("Acero inox 304 — 8400","8400"),
                ("Acero carbono — 7850","7850"),("Hierro fundido — 7800","7800")]
        self._mat_map = {m[0]:m[1] for m in mats}
        self.var_mat = tk.StringVar()
        cb = ttk.Combobox(f_mat, textvariable=self.var_mat,
                          values=[m[0] for m in mats], width=24,
                          state="readonly", font=("Courier New",8))
        cur_rho = str(int(self._params.get("rho_pesa",8000)))
        cb.set(next((m[0] for m in mats if m[1]==cur_rho), mats[0][0]))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", self._on_mat)
        self._sec(p, "④ Empuje del aire — boyancy (Tipo B)")
        self._fila(p, "ρ pesa — densidad (kg/m³)", "rho_pesa", unit="kg/m³")
        tk.Label(p, text="  ρ aire se toma del monitor HOBO en tiempo real",
                 bg=BG, fg=TXT_DIM, font=("Georgia",7,"italic")).pack(anchor="w",padx=6)
        self._sec(p, "⑤ Excentricidad / caracterización (Tipo B)")
        self._fila(p, "exc_max — diferencia máx. observada", "exc_max", unit="g")
        self._sec(p, "⑥ Deriva de la pesa (Tipo B)")
        self._fila(p, "Deriva estimada (mg)", "deriva", unit="mg")
        self._fila(p, "Nominal de la pesa (g)", "nominal", unit="g")

    def _build_resultados(self, p):
        tk.Label(p, text="COMPONENTES Y RESULTADO", bg=BG, fg=TXT_DIM,
                 font=("Georgia",8,"bold")).pack(anchor="w", pady=(0,4))
        tf = tk.Frame(p, bg=PANEL2, relief="flat", bd=1); tf.pack(fill="x", pady=(0,6))
        hdr_r = tk.Frame(tf, bg="#1a3a6b"); hdr_r.pack(fill="x")
        for col, w in [("FUENTE",28),("T",3),("u_i (mg)",10),("%",5),("ν",4)]:
            tk.Label(hdr_r, text=col, bg="#1a3a6b", fg="white",
                     font=("Courier New",7,"bold"),
                     width=w, anchor="w").pack(side="left", padx=2, pady=3)
        self._filas_comp = []
        fuentes = [("Repetibilidad  u_A = s/√n","A"),("Patrón  u_R = U_pat/2","B"),
                   ("Resolución  u_res = d/2√3","B"),("Empuje aire  u_B","B"),
                   ("Excentricidad  u_exc","B"),("Deriva pesa  u_D","B")]
        for i,(nombre,tipo) in enumerate(fuentes):
            bg_r = PANEL2 if i%2==0 else PANEL
            row = tk.Frame(tf, bg=bg_r); row.pack(fill="x")
            tk.Label(row, text=nombre, bg=bg_r, fg=TXT,
                     font=("Courier New",7), width=28, anchor="w").pack(side="left",padx=2,pady=2)
            tk.Label(row, text=tipo, bg=bg_r,
                     fg=ACCENT2 if tipo=="A" else TEAL,
                     font=("Courier New",7,"bold"), width=3).pack(side="left")
            lbu = tk.Label(row, text="—", bg=bg_r, fg="#22c55e",
                           font=("Courier New",8,"bold"), width=10, anchor="e")
            lbu.pack(side="left", padx=2)
            lbp = tk.Label(row, text="—", bg=bg_r, fg=TXT_DIM,
                           font=("Courier New",7), width=5, anchor="e")
            lbp.pack(side="left")
            lbn = tk.Label(row, text="—", bg=bg_r, fg=TXT_DIM,
                           font=("Courier New",7), width=4, anchor="e")
            lbn.pack(side="left", padx=2)
            self._filas_comp.append((lbu,lbp,lbn))
        tot = tk.Frame(tf, bg="#1a3a6b"); tot.pack(fill="x")
        self.lbl_totales = tk.Label(tot,
            text="u_c = — mg  |  ν_eff = —  |  k = —  |  U = — mg",
            bg="#1a3a6b", fg="#93c5fd", font=("Courier New",8,"bold"))
        self.lbl_totales.pack(anchor="w", padx=8, pady=4)
        met = tk.Frame(p, bg=BG); met.pack(fill="x", pady=(0,6))
        self._met = {}
        for key,lbl,unit in [("U_mg","U expandida","mg"),
                              ("k","Factor k","(k=2 si ν≥30)"),
                              ("ratio","U / MPE","≤0.333 ISO 17025")]:
            bx = tk.Frame(met, bg=PANEL2, padx=8, pady=6, relief="flat", bd=1)
            bx.pack(side="left", fill="x", expand=True, padx=3)
            tk.Label(bx, text=lbl, bg=PANEL2, fg=TXT_DIM, font=("Georgia",7)).pack()
            lv = tk.Label(bx, text="—", bg=PANEL2, fg=self.COLOR,
                          font=("Courier New",15,"bold"))
            lv.pack()
            tk.Label(bx, text=unit, bg=PANEL2, fg=TXT_DIM,
                     font=("Georgia",7,"italic")).pack()
            self._met[key] = lv
        self.lbl_kjust = tk.Label(p, text="", bg=PANEL2, fg=YELLOW,
                                   font=("Courier New",7),
                                   wraplength=460, justify="left",
                                   padx=8, pady=4)
        self.lbl_kjust.pack(fill="x", pady=(0,4))
        tk.Label(p, text="TEXTO PARA CERTIFICADO:", bg=BG, fg=TXT_DIM,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        cf = tk.Frame(p, bg=PANEL2, relief="flat", bd=1); cf.pack(fill="x", pady=(2,4))
        self.txt_cert = tk.Text(cf, height=7, width=58,
                                bg="#0a1525", fg="#94a3b8",
                                font=("Courier New",7),
                                relief="flat", bd=4,
                                state="disabled", wrap="word")
        self.txt_cert.pack(fill="x")

    def _build_historial(self, p):
        self._sec(p, "Historial calibraciones — seguimiento de deriva")
        hf = tk.Frame(p, bg=PANEL2, relief="flat", bd=1); hf.pack(fill="x", pady=(0,4))
        hh = tk.Frame(hf, bg="#1a3a6b"); hh.pack(fill="x")
        for col,w in [("FECHA",10),("Δm (mg)",9),("U (mg)",8),
                      ("DERIVA",8),("ESTADO",8),("CERTIFICADO",16)]:
            tk.Label(hh, text=col, bg="#1a3a6b", fg="white",
                     font=("Courier New",7,"bold"),
                     width=w, anchor="w").pack(side="left", padx=2, pady=3)
        self._hbody = tk.Frame(hf, bg=PANEL2); self._hbody.pack(fill="x")
        af = tk.Frame(p, bg=BG); af.pack(fill="x", pady=4)
        self._hvars = []
        for ph,w in [("dd/mm/aa",10),("Δm mg",8),("U mg",7),("N° Cert.",12)]:
            v = tk.StringVar(); self._hvars.append(v)
            tk.Entry(af, textvariable=v, width=w,
                     font=("Courier New",8), bg=PANEL2, fg=TXT,
                     insertbackground=self.COLOR,
                     relief="flat", bd=2).pack(side="left", padx=2)
        tk.Button(af, text="+ Agregar", bg=self.COLOR, fg="white",
                  font=("Georgia",8,"bold"), relief="flat", padx=8, pady=2,
                  command=self._add_hist).pack(side="left", padx=4)
        dm_f = tk.Frame(p, bg=BG); dm_f.pack(fill="x", pady=(4,0))
        self._dmet = {}
        for key,lbl in [("dm_actual","Δm actual"),("deriva_total","Deriva total"),("tendencia","Tendencia/ciclo")]:
            bx = tk.Frame(dm_f, bg=PANEL2, padx=8, pady=5, relief="flat", bd=1)
            bx.pack(side="left", fill="x", expand=True, padx=3)
            tk.Label(bx, text=lbl, bg=PANEL2, fg=TXT_DIM, font=("Georgia",7)).pack()
            lv = tk.Label(bx, text="—", bg=PANEL2, fg=self.COLOR,
                          font=("Courier New",13,"bold"))
            lv.pack()
            self._dmet[key] = lv
        self._render_hist()

    def _render_hist(self):
        for w in self._hbody.winfo_children(): w.destroy()
        MPE = 1000; prev = None
        for i,reg in enumerate(self._historial):
            bg_r = PANEL2 if i%2==0 else PANEL
            row = tk.Frame(self._hbody, bg=bg_r); row.pack(fill="x")
            dm = reg.get("dm",0)
            drift = (dm-prev) if prev is not None else None
            ds = (f"+{drift:.0f}" if drift>=0 else f"{drift:.0f}")+" mg" if drift is not None else "—"
            est = "OK" if dm<MPE/3 else ("Vigilar" if dm<MPE else "NO CONF.")
            col_e = GREEN if dm<MPE/3 else (YELLOW if dm<MPE else RED)
            for v,w in zip([reg.get("fecha","—"),f"{dm:.0f}",
                            f"±{reg.get('U',0):.0f}",ds,est,reg.get("cert","—")],
                           [10,9,8,8,8,16]):
                tk.Label(row, text=v, bg=bg_r,
                         fg=col_e if v==est else TXT,
                         font=("Courier New",7), width=w, anchor="w").pack(side="left",padx=2,pady=2)
            prev = dm
        if self._historial:
            dms=[r["dm"] for r in self._historial]; n=len(dms)
            dt=dms[-1]-dms[0] if n>1 else 0; tend=dt/(n-1) if n>1 else 0
            sg=lambda v:("+"+f"{v:.0f}") if v>=0 else f"{v:.0f}"
            self._dmet["dm_actual"].config(text=f"{dms[-1]:.0f} mg",
                fg=GREEN if dms[-1]<MPE/3 else (YELLOW if dms[-1]<MPE else RED))
            self._dmet["deriva_total"].config(text=f"{sg(dt)} mg",
                fg=YELLOW if abs(dt)>MPE/3 else GREEN)
            self._dmet["tendencia"].config(text=f"{sg(tend)} mg")

    def _add_hist(self):
        try:
            f=self._hvars[0].get().strip()
            dm=float(self._hvars[1].get().replace(",","."))
            U=float(self._hvars[2].get().replace(",",".") or "0")
            cert=self._hvars[3].get().strip()
            if not f: return
            self._historial.append({"fecha":f,"dm":dm,"U":U,"cert":cert})
            for v in self._hvars: v.set("")
            self._guardar_params(); self._render_hist()
        except ValueError:
            messagebox.showwarning("Datos inválidos","Verifica los valores.")

    def _on_change(self, key, var):
        try:
            self._params[key] = float(var.get().replace(",","."))
        except ValueError:
            pass
        self._calcular()

    def _on_mat(self, event=None):
        rho = self._mat_map.get(self.var_mat.get(),"8000")
        self._params["rho_pesa"] = float(rho)
        if hasattr(self,"var_rho_pesa"): self.var_rho_pesa.set(rho)
        self._calcular()

    def _guardar_y_recalc(self):
        self._guardar_params(); self._calcular()
        hablar("Parámetros GUM guardados")

    def _calcular(self):
        import math
        p = self._params
        n=max(2,int(float(str(p.get("n_series",5)))))
        s=float(str(p.get("s_rep",0.300)).replace(",","."))
        up=float(str(p.get("u_patron",0.060)).replace(",","."))
        d=float(str(p.get("d_bal",1.0)).replace(",","."))
        exc=float(str(p.get("exc_max",0.200)).replace(",","."))
        rp=float(str(p.get("rho_pesa",8000)).replace(",","."))/1000
        rr=float(str(p.get("rho_patron",8000)).replace(",","."))/1000
        der=float(str(p.get("deriva",50.0)).replace(",","."))/1000
        nom=float(str(p.get("nominal",20000)).replace(",","."))
        rho_a=0.0012
        try:
            rho_a=float(self.app.panel_ambiente.rho_last)/1000
        except Exception:
            pass
        u_A=s/math.sqrt(n); v_A=n-1
        u_R=up/2;            v_R=float('inf')
        u_res=d/(2*math.sqrt(3)); v_res=float('inf')
        dmB=nom*rho_a*(1/rp-1/rr)
        u_B=abs(dmB)/math.sqrt(3); v_B=float('inf')
        u_exc=exc/(2*math.sqrt(3)); v_exc=float('inf')
        u_D=der/math.sqrt(3);      v_D=float('inf')
        fuentes=[(u_A,v_A),(u_R,v_R),(u_res,v_res),(u_B,v_B),(u_exc,v_exc),(u_D,v_D)]
        uc2=sum(u**2 for u,v in fuentes)
        uc=math.sqrt(uc2)
        den=sum(u**4/v for u,v in fuentes if math.isfinite(v) and v>0)
        veff=min(uc2**2/den,9999) if den>0 else float('inf')
        T95={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,
             8:2.306,9:2.262,10:2.228,12:2.179,15:2.131,20:2.086,
             25:2.060,30:2.042,40:2.021,50:2.009,60:2.000,80:1.990,
             100:1.984,200:1.972,500:1.965}
        def gt(nu):
            if not math.isfinite(nu) or nu>=500: return 1.960
            nu=max(1,nu); ks=sorted(T95.keys())
            for i in range(len(ks)-1):
                if ks[i]<=nu<=ks[i+1]:
                    f=(nu-ks[i])/(ks[i+1]-ks[i])
                    return T95[ks[i]]+f*(T95[ks[i+1]]-T95[ks[i]])
            return 1.960
        t95=gt(veff); k=max(t95,2.00); U=k*uc; MPE=1.0; ratio=U/MPE
        for i,((lbu,lbp,lbn),(u,v)) in enumerate(zip(self._filas_comp,fuentes)):
            pct=u**2/uc2*100 if uc2>0 else 0
            lbu.config(text=f"{u*1000:.2f}")
            lbp.config(text=f"{pct:.0f}%")
            lbn.config(text="∞" if not math.isfinite(v) else str(int(v)))
        nu_s="∞" if not math.isfinite(veff) else f"{veff:.0f}"
        self.lbl_totales.config(
            text=f"u_c = {uc*1000:.1f} mg  |  ν_eff = {nu_s}  |  k = {k:.2f}  |  U = {U*1000:.1f} mg  (~95%)")
        self._met["U_mg"].config(text=f"{U*1000:.0f} mg",
            fg=GREEN if ratio<=1/3 else (YELLOW if ratio<=1 else RED))
        self._met["k"].config(text=f"{k:.2f}",
            fg=GREEN if k<=2.05 else YELLOW)
        self._met["ratio"].config(text=f"{ratio:.3f}",
            fg=GREEN if ratio<=1/3 else (YELLOW if ratio<=1 else RED))
        nu_d="∞" if not math.isfinite(veff) else f"{veff:.1f}"
        self.lbl_kjust.config(
            text=(f"ν_eff = {nu_d} ≥ 30 → t₀,₉₅ = {t95:.3f} → k = 2,00 JUSTIFICADO (GUM §G.6.4)"
                  if k<=2.05 else
                  f"⚠ ν_eff = {nu_d} bajo → t₀,₉₅ = {t95:.3f} → k = {k:.2f} REQUERIDO — aumentar n series"),
            fg=GREEN if k<=2.05 else YELLOW)
        cert_txt=(
            f"GUM (JCGM 100:2008) + EURAMET cg-18 v4 + PC-008 INACAL\n\n"
            f"  (A) Repetibilidad  u_A={u_A*1000:.1f} mg  [s={s*1000:.0f} mg, n={n}, ν={n-1}]\n"
            f"  (B) Patrón         u_R={u_R*1000:.1f} mg  [U={up*1000:.0f} mg, k=2, ν=∞]\n"
            f"  (B) Resolución     u_res={u_res*1000:.2f} mg  [d={d} g]\n"
            f"  (B) Empuje aire    u_B={u_B*1000:.2f} mg  [δmB={dmB*1000:.2f} mg]\n"
            f"  (B) Excentricidad  u_exc={u_exc*1000:.2f} mg  [exc={exc*1000:.0f} mg]\n"
            f"  (B) Deriva pesa    u_D={u_D*1000:.2f} mg  [D={der*1000:.0f} mg]\n\n"
            f"  u_c={uc*1000:.1f} mg  ν_eff={nu_s}  k={k:.2f}  U={U*1000:.0f} mg (~95%)"
        )
        self.txt_cert.config(state="normal")
        self.txt_cert.delete("1.0","end")
        self.txt_cert.insert("1.0", cert_txt.replace("\n",chr(10)))
        self.txt_cert.config(state="disabled")

# ════════════════════════════════════════════════════════════
#  APP PRINCIPAL
# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
#  PANEL WANT GT-30000TR — INGRESO MANUAL
# ════════════════════════════════════════════════════════════
class PanelWANT(tk.Frame):
    """
    Panel para balanza WANT GT-30000TR con ingreso manual por teclado.
    Capacidad: 30 000 g | Resolución: 0,1 g | Pesas: 10 kg, 20 kg, 25 kg
    """
    COLOR = "#7c3aed"  # Púrpura para distinguirla de las otras

    def __init__(self, parent, patrones_ref, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self.patrones       = patrones_ref
        self.paso_aba       = 0
        self.ir1 = self.it  = self.ir2 = None
        self.on_aba_completo = None
        self._build()

    def _build(self):
        tk.Frame(self, bg=self.COLOR, height=4).pack(fill="x")
        hdr = tk.Frame(self, bg=PANEL2, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text="WANT GT-30000TR", bg=PANEL2, fg=self.COLOR,
                 font=("Georgia",11,"bold")).pack(side="left")
        tk.Label(hdr, text="  Ingreso manual -- 30 000 g | d=0,1 g",
                 bg=PANEL2, fg=TXT_DIM, font=("Georgia",7,"italic")).pack(side="left")
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        col_l = tk.Frame(body, bg=PANEL2)
        col_l.pack(side="left", fill="both", padx=(0,3), ipadx=4)
        id_f = tk.Frame(col_l, bg=PANEL2, padx=10, pady=8)
        id_f.pack(fill="x")
        tk.Label(id_f, text="ID PESA", bg=PANEL2, fg=self.COLOR,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        self.e_desc = tk.Entry(id_f, width=20,
                               font=("Courier New",13,"bold"),
                               bg="#0d1f38", fg="#f0f0f0",
                               insertbackground=self.COLOR,
                               relief="flat", bd=0)
        self.e_desc.pack(fill="x", pady=(3,0))
        tk.Frame(id_f, bg=self.COLOR, height=2).pack(fill="x", pady=(3,0))
        tk.Label(id_f, text="Ingresa el codigo antes de iniciar",
                 bg=PANEL2, fg="#6b7280",
                 font=("Georgia",7,"italic")).pack(anchor="w", pady=(2,0))
        disp = tk.Frame(col_l, bg="#0a1525", padx=10, pady=14)
        disp.pack(fill="x")
        tk.Label(disp, text="Lectura (g):", bg="#0a1525", fg=TXT_DIM,
                 font=("Georgia",8)).pack(anchor="w")
        self.var_lectura = tk.StringVar()
        self.entry_lect = _entry_coma(disp, self.var_lectura,
                                       width=14,
                                       font=("Courier New",20,"bold"),
                                       bg="#0a1525", fg=GREEN,
                                       insertbackground=self.COLOR,
                                       relief="flat", bd=0,
                                       justify="right")
        self.entry_lect.pack(fill="x", pady=4)
        self.entry_lect.bind("<Return>",   self._on_enter)
        self.entry_lect.bind("<KP_Enter>", self._on_enter)
        self.entry_lect.focus_set()
        tk.Label(disp, text="Presiona Enter o KP-Enter para capturar",
                 bg="#0a1525", fg=TXT_DIM,
                 font=("Georgia",7,"italic")).pack(anchor="w")
        col_r = tk.Frame(body, bg=PANEL2)
        col_r.pack(side="left", fill="both", expand=True, padx=(3,0))
        pf = tk.Frame(col_r, bg=PANEL2, padx=10, pady=8)
        pf.pack(fill="x")
        tk.Frame(pf, bg=self.COLOR, height=2).pack(fill="x", pady=(0,5))
        tk.Label(pf, text="PATRON DE REFERENCIA", bg=PANEL2, fg=self.COLOR,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        row_pat = tk.Frame(pf, bg=PANEL2); row_pat.pack(fill="x", pady=(4,0))
        tk.Label(row_pat, text="Patron:", bg=PANEL2, fg=TXT,
                 font=FN_UI).pack(side="left")
        self.combo_pat = ttk.Combobox(row_pat, width=24, state="readonly")
        self.combo_pat.pack(side="left", padx=6)
        self.combo_pat.bind("<<ComboboxSelected>>", self._on_patron)
        self.lbl_pat_info = tk.Label(pf, text="Nominal: --  |  delta_mcr: --  |  Cert.: --",
                                     bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
        self.lbl_pat_info.pack(anchor="w", pady=(2,0))
        self.lbl_pat_venc = tk.Label(pf, text="Vence: --",
                                     bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
        self.lbl_pat_venc.pack(anchor="w")
        self.lbl_emp_info = tk.Label(pf, text="EMP clase M2: --",
                                     bg=PANEL2, fg=YELLOW, font=("Courier New",8,"bold"))
        self.lbl_emp_info.pack(anchor="w")
        self.actualizar_patrones()
        aba = tk.Frame(col_r, bg=PANEL2, padx=10, pady=8)
        aba.pack(fill="x")
        tk.Frame(aba, bg=self.COLOR, height=2).pack(fill="x", pady=(0,5))
        tk.Label(aba, text="PROCEDIMIENTO ABA -- INGRESO MANUAL",
                 bg=PANEL2, fg=self.COLOR, font=("Georgia",7,"bold")).pack(anchor="w")
        fml = tk.Frame(aba, bg="#0a1525", padx=8, pady=5)
        fml.pack(fill="x", pady=(3,6))
        tk.Label(fml, text="delta_mct = It - (Ir1+Ir2)/2 + delta_mcr",
                 bg="#0a1525", fg=self.COLOR,
                 font=("Courier New",9,"bold")).pack()
        self.lbl_paso = tk.Label(aba, text="Presiona Iniciar ABA",
                                 bg=PANEL2, fg=TXT_DIM,
                                 font=("Courier New",8,"bold"),
                                 wraplength=700, justify="left")
        self.lbl_paso.pack(anchor="w", pady=(4,3))
        vals_f = tk.Frame(aba, bg="#0a1525", padx=8, pady=6)
        vals_f.pack(fill="x", pady=(0,4))
        for lbl_txt, attr in [("Ir1 -- Patron A1:","lbl_ir1"),
                               ("It  -- Incognita B:","lbl_it"),
                               ("Ir2 -- Patron A2:","lbl_ir2")]:
            f2 = tk.Frame(vals_f, bg="#0a1525"); f2.pack(fill="x", pady=1)
            tk.Label(f2, text=lbl_txt, bg="#0a1525", fg=TXT_DIM,
                     font=("Courier New",8), width=22, anchor="w").pack(side="left")
            lv = tk.Label(f2, text="--", bg="#0a1525", fg=GREEN,
                          font=("Courier New",10,"bold"), anchor="e")
            lv.pack(side="left", fill="x", expand=True)
            setattr(self, attr, lv)
        self.lbl_res = tk.Label(aba, text="--",
                                bg=PANEL2, fg=GREEN,
                                font=("Courier New",9,"bold"),
                                wraplength=700, justify="left")
        self.lbl_res.pack(anchor="w", pady=(0,8))
        btns = tk.Frame(aba, bg=PANEL2); btns.pack(fill="x")
        self.btn_iniciar = tk.Button(btns, text="Iniciar ABA",
                                     bg=self.COLOR, fg="white",
                                     font=("Georgia",9,"bold"),
                                     relief="flat", padx=16, pady=6,
                                     command=self.iniciar_aba)
        self.btn_iniciar.pack(side="left", padx=(0,8))
        self.btn_capturar = tk.Button(btns, text="Capturar (Enter)",
                                      bg="#166534", fg="white",
                                      font=("Georgia",9,"bold"),
                                      relief="flat", padx=16, pady=6,
                                      state="disabled", command=self.capturar)
        self.btn_capturar.pack(side="left", padx=(0,8))
        tk.Button(btns, text="Cancelar",
                  bg=PANEL, fg=TXT_DIM,
                  font=("Georgia",8), relief="flat",
                  padx=10, pady=6,
                  command=self.cancelar_aba).pack(side="left")
        lf = tk.Frame(aba, bg=PANEL2, pady=4); lf.pack(fill="x")
        self.led_cv = tk.Canvas(lf, width=16, height=16,
                                bg=PANEL2, highlightthickness=0)
        self.led_cv.pack(side="left", padx=(0,5))
        self._led_dot = self.led_cv.create_oval(1,1,15,15,
                                                fill="#1a1a1a", outline="#374151")
        self.lbl_led = tk.Label(lf, text="CICLO ABA INICIADO",
                                bg=PANEL2, fg="#374151",
                                font=("Georgia",7,"bold"))
        self.lbl_led.pack(side="left")
        self._led_on = False; self._led_blink = False
    # ── Métodos ──────────────────────────────────────────────
    def actualizar_patrones(self):
        # Mostrar todos los patrones — operador elige el apropiado
        vals = [f"{p['id']} ({p['nominal']}g)" for p in self.patrones]
        self.combo_pat["values"] = vals
        self._patrones_filtrados = self.patrones
        if vals:
            self.combo_pat.current(0)
            self._on_patron()

    def _on_patron(self, event=None):
        idx = self.combo_pat.current()
        pts = getattr(self, '_patrones_filtrados', self.patrones)
        if idx < 0 or idx >= len(pts): return
        p = pts[idx]
        est, color, dias = estado_vigencia(p["vencimiento"])
        self.lbl_pat_info.config(
            text=f"Nominal: {fmt(p['nominal'],1)} g  |  "
                 f"delta_mcr: {fmt(p['dcr'],4,True)} g  |  Cert.: {p['n_cert']}")
        self.lbl_pat_venc.config(
            text=f"Vence: {p['vencimiento']}  —  {est} ({abs(dias)}d)",
            fg=color)
        emp = obtener_emp_m2_directo(p["nominal"])
        if emp:
            self.lbl_emp_info.config(
                text=f"EMP clase M2: ±{fdc(emp,3)} mg  (NMP 004:2007)",
                fg=YELLOW)

    def _patron_actual(self):
        idx  = self.combo_pat.current()
        pts  = getattr(self, '_patrones_filtrados', self.patrones)
        if idx < 0 or idx >= len(pts): return None
        return pts[idx]

    def _get_valor(self):
        """Parsea el valor del Entry con coma decimal."""
        txt = self.var_lectura.get().replace(",", ".")
        try:
            v = float(txt)
            if 0 <= v <= 30000:
                return v
            messagebox.showwarning("Fuera de rango",
                f"Valor {txt} fuera del rango WANT (0–30 000 g).")
            return None
        except ValueError:
            messagebox.showwarning("Valor inválido",
                "Ingresa un número válido.")
            return None

    def _on_enter(self, event=None):
        """Enter o KP-Enter captura el valor si ABA está activo."""
        if self.paso_aba > 0 and self.btn_capturar.cget("state") == "normal":
            self.capturar()
        elif self.paso_aba == 0:
            # Mostrar el valor ingresado como lectura actual
            v = self._get_valor()
            if v is not None:
                pass  # solo validar

    def iniciar_aba(self):
        if not self._patron_actual():
            messagebox.showwarning("Sin patron",
                "Selecciona un patron.")
            return
        self.paso_aba = 1
        self.ir1 = self.it = self.ir2 = None
        self.lbl_ir1.config(text="--"); self.lbl_it.config(text="--")
        self.lbl_ir2.config(text="--"); self.lbl_res.config(text="--")
        self.btn_capturar.config(state="normal")
        self.btn_iniciar.config(state="disabled")
        self._led_blink = True; self._led_on = False
        self.lbl_led.config(text="CICLO ABA INICIADO", fg="#ef4444")
        self._tick_led()
        self.var_lectura.set("")
        self.entry_lect.focus_set()
        self._actualizar_paso()

    def _actualizar_paso(self):
        msgs = {
            1: "Paso 1/3 — Coloca PESA PATRON → Lee pantalla → Enter",
            2: "Paso 2/3 — Coloca PESA INCOGNITA → Lee pantalla → Enter",
            3: "Paso 3/3 — Coloca PESA PATRON → Lee pantalla → Enter",
        }
        self.lbl_paso.config(
            text=msgs.get(self.paso_aba, ""),
            fg=self.COLOR)

    def capturar(self):
        v = self._get_valor()
        if v is None: return
        d = 1  # resolución 0,1 g
        if self.paso_aba == 1:
            self.ir1 = v
            self.lbl_ir1.config(text=f"{fmt(v,d)} g")
            self.paso_aba = 2
        elif self.paso_aba == 2:
            self.it  = v
            self.lbl_it.config(text=f"{fmt(v,d)} g")
            self.paso_aba = 3
        elif self.paso_aba == 3:
            self.ir2 = v
            self.lbl_ir2.config(text=f"{fmt(v,d)} g")
            self._calcular_aba()
            return
        self.var_lectura.set("")
        self.entry_lect.focus_set()
        self._actualizar_paso()

    def _calcular_aba(self):
        pat    = self._patron_actual()
        if not pat: return
        ir_prom = (self.ir1 + self.ir2) / 2.0
        dct     = self.it - ir_prom + pat["dcr"]
        dct_mg  = abs(dct) * 1000
        emp_mg  = obtener_emp_m2_directo(pat["nominal"])
        conforme = dct_mg <= emp_mg if emp_mg else True
        emp_txt  = fdc(emp_mg, 3) if emp_mg else "—"
        estado   = "CONFORME" if conforme else "NO CONFORME"
        d = 1
        self.lbl_res.config(
            text=(f"Ir_prom = {fmt(ir_prom,d)} g\n"
                  f"delta_mct = {fmt(dct,d,True)} g  "
                  f"({fdc(dct_mg,3,True)} mg)\n"
                  f"EMP M2: {emp_txt}  →  {estado}"),
            fg=GREEN if conforme else RED)
        self.btn_capturar.config(state="disabled")
        self.btn_iniciar.config(state="normal")
        self._led_blink = False
        self.led_cv.itemconfig(self._led_dot, fill="#22c55e", outline="#16a34a")
        self.lbl_led.config(text="ABA COMPLETADO", fg="#22c55e")
        self.lbl_paso.config(text=f"ABA completado -- {estado}",
                             fg=GREEN if conforme else RED)
        self.paso_aba = 0
        self.var_lectura.set("")
        # Anuncio de voz
        hablar("Ciclo A, B, A... Completado")
        if self.on_aba_completo:
            self.on_aba_completo({
                "balanza":       "WANT GT-30000TR",
                "id_pesa":       self.e_desc.get().strip() or "pesa",
                "patron_id":     pat["id"],
                "nominal":       pat["nominal"],
                "n_cert":        pat["n_cert"],
                "ir1":  self.ir1, "it":  self.it, "ir2": self.ir2,
                "ir_prom": ir_prom, "dct": dct, "dcr": pat["dcr"],
                "decimales":     d,
                "dct_mg":        round(dct_mg, 3),
                "emp_mg":        emp_mg,
                "conforme_emp":  conforme,
            })

    def cancelar_aba(self):
        self.paso_aba = 0
        self.btn_capturar.config(state="disabled")
        self.btn_iniciar.config(state="normal")
        self._led_blink = False
        self.led_cv.itemconfig(self._led_dot, fill="#1a1a1a", outline="#374151")
        self.lbl_led.config(text="CICLO ABA INICIADO", fg="#374151")
        self.lbl_paso.config(text="Presiona Iniciar ABA", fg=TXT_DIM)
        self.lbl_res.config(text="--")
        self.var_lectura.set("")
        self.entry_lect.focus_set()

    def _tick_led(self):
        if not self._led_blink: return
        self._led_on = not self._led_on
        self.led_cv.itemconfig(self._led_dot,
            fill="#ef4444" if self._led_on else "#7f1d1d",
            outline="#fca5a5" if self._led_on else "#450a0a")
        self.after(400, self._tick_led)



# ─── NMP 004:2007 — Pesas M2 por balanza ─────────────────────
# (nominal_g, etiqueta, EMP_mg, decimales_display)
PESAS_RADWAG = [
    (0.1,   "100 mg",  0.20,  4),
    (0.2,   "200 mg",  0.30,  4),
    (0.5,   "500 mg",  0.75,  4),
    (1.0,   "1 g",     1.5,   4),
    (2.0,   "2 g",     3.0,   4),
    (5.0,   "5 g",     5.0,   4),
    (10.0,  "10 g",    10.0,  4),
    (20.0,  "20 g",    25.0,  4),
    (50.0,  "50 g",    50.0,  4),
    (100.0, "100 g",   100.0, 4),
    (200.0, "200 g",   150.0, 4),
]
PESAS_BIOBASE = [
    (100.0,  "100 g",  100.0, 2),
    (200.0,  "200 g",  150.0, 2),
    (500.0,  "500 g",  250.0, 2),
    (1000.0, "1 kg",   500.0, 2),
    (2000.0, "2 kg",  1000.0, 2),
    (5000.0, "5 kg",  2500.0, 2),
]
PESAS_WANT = [
    (5000.0,  "5 kg",  2500.0, 1),
    (10000.0, "10 kg", 5000.0, 1),
    (20000.0, "20 kg",10000.0, 1),
    (25000.0, "25 kg",10000.0, 1),
]
N_LECTURAS_CARAC = 10

# Constantes de fuente para PanelCarac
FN_BOLD = ("Georgia", 9, "bold")
FN_MONO = ("Courier New", 10)

# Archivos historial caracterizacion
import os as _os
FILE_HIST_CARAC = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__))
    if "__file__" in dir() else ".",
    "historial_carac.json")

def fmt_carac(v, d=4):
    return format(v, f".{d}f").replace(".", ",")

def fmt_stat_carac(v, d=15):
    return format(v, f".{d}f").replace(".", ",")

def delta_i_carac(ir1, it, ir2):
    return it - (ir1 + ir2) / 2.0

def s_delta_carac(lecturas):
    if len(lecturas) < 2: return 0.0
    deltas = [delta_i_carac(l["ir1"], l["it"], l["ir2"]) for l in lecturas]
    n = len(deltas); mean = sum(deltas) / n
    import math
    return math.sqrt(sum((d - mean) ** 2 for d in deltas) / (n - 1))

def varianza_carac(sdis):
    n = len(sdis)
    if n < 2: return None
    mean = sum(sdis) / n
    return sum((s - mean) ** 2 for s in sdis) / (n - 1)

def cargar_hist_carac():
    try:
        with open(FILE_HIST_CARAC, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def guardar_hist_carac(h):
    with open(FILE_HIST_CARAC, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)

ORDINAL_CARAC = {1:"primer",2:"segundo",3:"tercer",
                 4:"cuarto",5:"quinto",6:"sexto",
                 7:"septimo",8:"octavo",9:"noveno",10:"decimo"}



class PanelCarac(tk.Frame):
    """
    Panel completo de caracterización para una balanza.
    Se instancia una vez por balanza dentro de cada pestaña.
    """
    def __init__(self, parent, cfg, hist_ref,
                 on_hist_change, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.cfg          = cfg   # dict con config balanza
        self.hist         = hist_ref
        self.on_hist_change = on_hist_change

        self.cx           = None
        self.paso         = 0
        self.lecturas     = []
        self.tmp_ir1      = None
        self.tmp_it       = None
        self.ultimo_sdi   = None

        self._build()

    def _build(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # Col izquierda
        col_izq = tk.Frame(body, bg=BG, width=420)
        col_izq.pack(side="left", fill="y", padx=(0,6))
        col_izq.pack_propagate(False)

        # Col derecha
        col_der = tk.Frame(body, bg=BG)
        col_der.pack(side="right", fill="both", expand=True)

        self._ui_conexion(col_izq)
        self._ui_selector(col_izq)
        self._ui_ciclo(col_izq)
        self._ui_historial(col_der)
        self._ui_grafico(col_der)

    # ── Helpers ──────────────────────────────────────────────
    def _panel(self, parent, titulo, color=None,
               expand=False):
        c=color or ACCENT
        outer=tk.Frame(parent, bg=BORDER)
        outer.pack(fill="x" if not expand else "both",
                   expand=expand, pady=(0,5))
        tk.Frame(outer, bg=c, width=3).pack(
            side="left", fill="y")
        inner=tk.Frame(outer, bg=PANEL, padx=9, pady=7)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=titulo.upper(),
                 bg=PANEL, fg=c,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(inner, bg=BORDER,
                 height=1).pack(fill="x", pady=(2,5))
        return inner

    # ── Conexión ─────────────────────────────────────────────
    def _ui_conexion(self, parent):
        color = self.cfg["color"]
        p = self._panel(parent, "Conexión", color)

        tipo = self.cfg["tipo"]  # "serial" o "wifi"

        if tipo == "serial":
            row=tk.Frame(p, bg=PANEL)
            row.pack(fill="x", pady=(0,4))
            tk.Label(row, text="Puerto:", bg=PANEL,
                     fg=TXT, font=FN_UI).pack(side="left")
            self.combo_port=ttk.Combobox(
                row, width=7, state="readonly")
            puertos=[x.device for x in
                     serial.tools.list_ports.comports()]
            self.combo_port["values"]=puertos
            dflt=self.cfg.get("puerto","COM6")
            self.combo_port.set(
                dflt if dflt in puertos
                else (puertos[0] if puertos else ""))
            self.combo_port.pack(side="left", padx=4)
            tk.Label(row, text="Baud:", bg=PANEL,
                     fg=TXT, font=FN_UI).pack(side="left")
            self.combo_baud=ttk.Combobox(
                row, width=6, state="readonly",
                values=["9600","19200","4800","2400"])
            self.combo_baud.set(
                str(self.cfg.get("baud",9600)))
            self.combo_baud.pack(side="left", padx=4)
            tk.Button(row, text="↺", bg=PANEL2,
                      fg=TXT_DIM, font=("Georgia",10),
                      relief="flat",
                      command=self._refresh_ports).pack(
                side="left", padx=2)

        elif tipo == "wifi":
            row=tk.Frame(p, bg=PANEL)
            row.pack(fill="x", pady=(0,4))
            tk.Label(row, text="IP:", bg=PANEL,
                     fg=TXT, font=FN_UI).pack(side="left")
            self.e_ip=tk.Entry(row, width=14,
                font=("Courier New",9), bg=PANEL2,
                fg=TXT, insertbackground=color,
                relief="flat", bd=2)
            self.e_ip.insert(0, self.cfg.get(
                "ip", RADWAG_IP))
            self.e_ip.pack(side="left", padx=4)
            tk.Label(row, text="Puerto:", bg=PANEL,
                     fg=TXT, font=FN_UI).pack(side="left")
            self.e_wport=tk.Entry(row, width=5,
                font=("Courier New",9), bg=PANEL2,
                fg=TXT, insertbackground=color,
                relief="flat", bd=2)
            self.e_wport.insert(0, str(self.cfg.get(
                "port", RADWAG_PORT)))
            self.e_wport.pack(side="left", padx=4)

        self.btn_cx=tk.Button(p,
            text="▶ Conectar",
            bg=color, fg="white",
            font=FN_BOLD, relief="flat",
            padx=10, pady=3,
            command=self._toggle_cx)
        self.btn_cx.pack(fill="x", pady=(0,2))
        self.lbl_cx=tk.Label(p,
            text="⚫ Desconectado",
            bg=PANEL, fg=RED, font=FN_SM)
        self.lbl_cx.pack(anchor="w")

        # Display en vivo
        dd = self.cfg["decimales_display"]
        ceros = "0" * dd
        self.lbl_live=tk.Label(p,
            text=f"--,{ceros} g",
            bg=PANEL, fg=GREEN, font=FN_BIG)
        self.lbl_live.pack(pady=(5,0))
        self.lbl_raw=tk.Label(p, text="raw: —",
            bg=PANEL, fg=TXT_DIM,
            font=("Courier New",7))
        self.lbl_raw.pack()

    def _refresh_ports(self):
        p=[x.device for x in
           serial.tools.list_ports.comports()]
        self.combo_port["values"]=p

    def _toggle_cx(self):
        color=self.cfg["color"]
        tipo =self.cfg["tipo"]
        if self.cx and getattr(self.cx,"activo",False):
            self.cx.desconectar()
            self.cx=None
            self.btn_cx.config(
                text="▶ Conectar", bg=color)
            self.lbl_cx.config(
                text="⚫ Desconectado", fg=RED)
        else:
            if tipo=="serial":
                puerto=self.combo_port.get()
                baud=int(self.combo_baud.get())
                self.cx=ConexionSerial(
                    on_dato=self._on_dato)
                ok=self.cx.conectar(puerto, baud)
                if ok:
                    self.btn_cx.config(
                        text="⏹ Desconectar", bg=RED)
                    self.lbl_cx.config(
                        text=f"🟢 {puerto} @ {baud}",
                        fg=GREEN)
                else:
                    messagebox.showerror(
                        "Conexión",
                        f"No se pudo abrir {puerto}.")
                    self.cx=None
            elif tipo=="wifi":
                ip=self.e_ip.get().strip()
                port=int(self.e_wport.get().strip())
                self.cx=ConexionRadwag(
                    on_dato=self._on_dato)
                self.cx.conectar(ip, port)
                self.btn_cx.config(
                    text="⏹ Desconectar", bg=RED)
                self.lbl_cx.config(
                    text=f"🟢 WiFi {ip}:{port}",
                    fg=GREEN)

    def _on_dato(self, valor, raw):
        self.after(0, self._procesar, valor, raw)

    def _procesar(self, valor, raw):
        if raw=="__CONNECTED__":
            self.lbl_cx.config(
                text=f"🟢 WiFi conectado", fg=GREEN)
            return
        if raw=="__DISCONNECTED__":
            self.lbl_cx.config(
                text="🔄 Reconectando...", fg=YELLOW)
            return
        if valor is None: return
        dd=self.cfg["decimales_display"]
        self.lbl_live.config(
            text=f"{fmt_carac(valor,dd)} g",
            fg=GREEN)
        self.lbl_raw.config(
            text=f"raw: {str(raw)[:45]}")
        if self.paso>0:
            self._recibir_print(valor)

    # ── Selector de pesa ─────────────────────────────────────
    def _ui_selector(self, parent):
        color=self.cfg["color"]
        p=self._panel(parent, "Pesa a caracterizar",
                      TEAL)
        tk.Label(p, text="Selecciona la pesa:",
                 bg=PANEL, fg=TXT, font=FN_UI).pack(
            anchor="w")
        pesas=self.cfg["pesas"]
        etiquetas=[f"{pw[1]}  (EMP ±{pw[2]} mg)"
                   for pw in pesas]
        self.combo_pesa=ttk.Combobox(
            p, width=30, state="readonly",
            values=etiquetas)
        self.combo_pesa.set(etiquetas[0])
        self.combo_pesa.pack(fill="x", pady=(4,6))
        self.combo_pesa.bind(
            "<<ComboboxSelected>>", self._on_pesa)

        # Datos patrón
        tk.Frame(p, bg=BORDER, height=1).pack(
            fill="x", pady=(0,5))
        tk.Label(p, text="DATOS DE LA PESA PATRÓN",
                 bg=PANEL, fg=TEAL,
                 font=("Georgia",7,"bold")).pack(
            anchor="w", pady=(0,4))

        def campo(lbl, attr, val=""):
            row=tk.Frame(p, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, bg=PANEL, fg=TXT,
                     font=FN_UI, width=14,
                     anchor="w").pack(side="left")
            e=tk.Entry(row, font=("Courier New",9),
                       bg=PANEL2, fg=TXT,
                       insertbackground=TEAL,
                       relief="flat", bd=2, width=20)
            e.insert(0, val)
            e.pack(side="left", padx=4)
            setattr(self, attr, e)

        campo("ID / Código:",    "e_pat_id")
        campo("N° Certificado:", "e_pat_cert")
        campo("Fecha Cal.:",     "e_pat_fecha",
              datetime.now().strftime("%Y-%m-%d"))

        tk.Frame(p, bg=BORDER, height=1).pack(
            fill="x", pady=(5,5))
        self.lbl_ciclos_info=tk.Label(p,
            text="Ciclos guardados: 0",
            bg=PANEL, fg=TXT_DIM, font=FN_SM)
        self.lbl_ciclos_info.pack(anchor="w")
        self.lbl_var_hist=tk.Label(p,
            text="Varianza entre ciclos: —",
            bg=PANEL, fg=TXT_DIM,
            font=("Courier New",8,"bold"))
        self.lbl_var_hist.pack(anchor="w")

        tk.Button(p,
            text="▶  Iniciar nueva caracterización",
            bg=TEAL, fg="white",
            font=FN_BOLD, relief="flat",
            padx=10, pady=5,
            command=self._iniciar).pack(
            fill="x", pady=(8,0))

    def _key(self):
        idx=self.combo_pesa.current()
        pesas=self.cfg["pesas"]
        if 0<=idx<len(pesas):
            return f"{self.cfg['nombre']}_{pesas[idx][1]}"
        return f"{self.cfg['nombre']}_?"

    def _decimales(self):
        idx=self.combo_pesa.current()
        pesas=self.cfg["pesas"]
        if 0<=idx<len(pesas):
            return pesas[idx][3]
        return 2

    def _on_pesa(self, event=None):
        self._upd_info_pesa()
        self._upd_historial()
        self._upd_grafico()

    def _upd_info_pesa(self):
        key=self._key()
        ciclos=self.hist.get(key,{}).get("ciclos",[])
        n=len(ciclos)
        self.lbl_ciclos_info.config(
            text=f"Ciclos guardados: {n}")
        if n>=2:
            sdis=[c["sdi"] for c in ciclos]
            var=varianza_carac(sdis)
            self.lbl_var_hist.config(
                text=f"Varianza: {fmt_stat_carac(var)} g²",
                fg=GREEN if var<1e-4 else YELLOW)
        else:
            self.lbl_var_hist.config(
                text="Varianza: — (mín. 2 ciclos)",
                fg=TXT_DIM)

    # ── Panel ciclo ──────────────────────────────────────────
    def _ui_ciclo(self, parent):
        color=self.cfg["color"]
        p=self._panel(parent,
                      "Ciclo actual — lecturas en vivo",
                      color)

        self.lbl_paso=tk.Label(p,
            text="▶  Presiona 'Iniciar nueva "
                 "caracterización'",
            bg=PANEL, fg=TXT_DIM,
            font=("Courier New",8,"bold"),
            wraplength=380, justify="left")
        self.lbl_paso.pack(anchor="w", pady=(0,5))

        # Parcial en vivo
        parcial=tk.Frame(p, bg="#0a1525",
                         padx=8, pady=6)
        parcial.pack(fill="x", pady=(0,4))
        fila_p=tk.Frame(parcial, bg="#0a1525")
        fila_p.pack(fill="x")
        for txt, attr in [
                ("Ir1:","lbl_p_ir1"),
                ("It:", "lbl_p_it"),
                ("Ir2:","lbl_p_ir2")]:
            tk.Label(fila_p, text=txt,
                     bg="#0a1525", fg=TXT_DIM,
                     font=FN_SM).pack(
                side="left", padx=(0,2))
            lv=tk.Label(fila_p, text="—",
                        bg="#0a1525", fg=TXT_DIM,
                        font=("Courier New",9,"bold"),
                        width=10)
            lv.pack(side="left", padx=(0,10))
            setattr(self, attr, lv)

        self.lbl_di_full=tk.Label(parcial,
            text="ΔI: —", bg="#0a1525", fg=ACCENT,
            font=("Courier New",8,"bold"))
        self.lbl_di_full.pack(anchor="w", pady=(4,0))

        self.lbl_n=tk.Label(p,
            text=f"0 / {N_LECTURAS_CARAC} lecturas",
            bg=PANEL, fg=TXT_DIM,
            font=("Courier New",8))
        self.lbl_n.pack(anchor="w", pady=(0,4))

        # Tabla
        cols=("N°","PATRÓN Ir1","CALIBRAR It",
              "PATRÓN Ir2","ΔI")
        self.tbl_ciclo=ttk.Treeview(
            p, columns=cols,
            show="headings", height=6)
        for col, w in zip(cols,[28,100,100,100,80]):
            self.tbl_ciclo.heading(col, text=col)
            self.tbl_ciclo.column(col, width=w,
                anchor="center", minwidth=w)
        sb=ttk.Scrollbar(p, orient="vertical",
            command=self.tbl_ciclo.yview)
        sb.pack(side="right", fill="y")
        self.tbl_ciclo.configure(yscrollcommand=sb.set)
        self.tbl_ciclo.pack(fill="x")

        tk.Frame(p, bg=BORDER,
                 height=1).pack(fill="x", pady=(6,4))

        # s(ΔI)
        row_sdi=tk.Frame(p, bg=PANEL)
        row_sdi.pack(fill="x", pady=2)
        tk.Label(row_sdi, text="s(ΔI) :", bg=PANEL,
                 fg=TXT, font=("Georgia",9,"bold"),
                 width=16, anchor="e").pack(side="left")
        self.lbl_sdi=tk.Label(row_sdi, text="—",
            bg=PANEL2, fg=ACCENT,
            font=("Courier New",9,"bold"),
            anchor="w", padx=8, pady=3,
            relief="flat", width=24)
        self.lbl_sdi.pack(side="left", padx=6)
        tk.Label(row_sdi, text="g", bg=PANEL,
                 fg=TXT_DIM, font=FN_SM).pack(
            side="left")

        # Varianza
        row_var=tk.Frame(p, bg=PANEL)
        row_var.pack(fill="x", pady=2)
        tk.Label(row_var, text="Varianza de ΔI :",
                 bg=PANEL, fg=TXT,
                 font=("Georgia",9,"bold"),
                 width=16, anchor="e").pack(side="left")
        self.lbl_var_ciclo=tk.Label(row_var, text="—",
            bg=TEAL, fg="white",
            font=("Courier New",9,"bold"),
            anchor="w", padx=8, pady=3,
            relief="flat", width=24)
        self.lbl_var_ciclo.pack(side="left", padx=6)
        tk.Label(row_var,
                 text="g²  Para 2+ ciclos",
                 bg=PANEL, fg=TXT_DIM,
                 font=FN_SM).pack(side="left")

    # ── Historial ────────────────────────────────────────────
    def _ui_historial(self, parent):
        p=self._panel(parent, "Historial de ciclos")
        cols=("N°","Pesa","Fecha",
              "ID Patrón","N° Cert.",
              "s(ΔI) g","Varianza g²")
        self.tbl_hist=ttk.Treeview(
            p, columns=cols,
            show="headings", height=5)
        for col,w in zip(cols,
                [28,60,140,90,100,150,150]):
            self.tbl_hist.heading(col, text=col)
            self.tbl_hist.column(col, width=w,
                anchor="center", minwidth=28)
        sy=ttk.Scrollbar(p, orient="vertical",
            command=self.tbl_hist.yview)
        sx=ttk.Scrollbar(p, orient="horizontal",
            command=self.tbl_hist.xview)
        self.tbl_hist.configure(
            yscrollcommand=sy.set,
            xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        self.tbl_hist.pack(fill="both", expand=True)
        sx.pack(fill="x")

    # ── Gráfico ──────────────────────────────────────────────
    def _ui_grafico(self, parent):
        p=self._panel(parent,
                      "Tendencia s(ΔI) por ciclo",
                      PURPLE, expand=True)
        self.fig=Figure(figsize=(5,2.8),
                        facecolor="#0f1828")
        self.ax=self.fig.add_subplot(111)
        self._estilo_ax()
        self.canvas=FigureCanvasTkAgg(
            self.fig, master=p)
        self.canvas.get_tk_widget().pack(
            fill="both", expand=True)

    def _estilo_ax(self):
        self.ax.clear()
        self.ax.set_facecolor("#0a1525")
        self.ax.tick_params(colors="#4a6480",
                            labelsize=8)
        for sp in ["bottom","left"]:
            self.ax.spines[sp].set_color("#1a2940")
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.ax.set_xlabel("Ciclo",
            color="#4a6480", fontsize=8)
        self.ax.set_ylabel("s(ΔI) g",
            color="#4a6480", fontsize=8)
        self.ax.grid(color="#1a2940",
            linestyle="--", linewidth=0.5)

    # ── Iniciar ──────────────────────────────────────────────
    def _iniciar(self):
        if not self.cx or \
                not getattr(self.cx,"activo",False):
            messagebox.showwarning(
                "Sin conexión",
                "Conecta la balanza primero.")
            return
        self.paso=1; self.lecturas=[]
        self.tmp_ir1=None; self.tmp_it=None
        self.ultimo_sdi=None
        for i in self.tbl_ciclo.get_children():
            self.tbl_ciclo.delete(i)
        self.lbl_p_ir1.config(text="—", fg=TXT_DIM)
        self.lbl_p_it.config(text="—",  fg=TXT_DIM)
        self.lbl_p_ir2.config(text="—", fg=TXT_DIM)
        self.lbl_di_full.config(text="ΔI: —",
                                fg=ACCENT)
        self.lbl_sdi.config(text="—", fg=ACCENT)
        self.lbl_var_ciclo.config(text="—",
                                  fg="white")
        self.lbl_n.config(
            text=f"0 / {N_LECTURAS_CARAC} lecturas",
            fg=TXT_DIM)
        self._upd_paso()

    def _upd_paso(self):
        n=len(self.lecturas)+1
        msgs={
            1:f"📍 Lect. {n}/{N_LECTURAS_CARAC} — "
              f"Ir1: PATRÓN → PRINT",
            2:f"📍 Lect. {n}/{N_LECTURAS_CARAC} — "
              f"It: PESA CALIBRAR → PRINT",
            3:f"📍 Lect. {n}/{N_LECTURAS_CARAC} — "
              f"Ir2: PATRÓN → PRINT",
        }
        self.lbl_paso.config(
            text=msgs.get(self.paso,
                "▶  Presiona 'Iniciar nueva "
                "caracterización'"),
            fg=YELLOW if self.paso>0 else TXT_DIM)

    # ── Recibir dato ─────────────────────────────────────────
    def _recibir_print(self, valor):
        if self.paso==0: return
        dd=self._decimales()

        if self.paso==1:
            self.tmp_ir1=valor; self.paso=2
            self.lbl_p_ir1.config(
                text=fmt_carac(valor,dd)+" g",
                fg=GREEN)
            self.lbl_p_it.config(text="—",
                                 fg=TXT_DIM)
            self.lbl_p_ir2.config(text="—",
                                  fg=TXT_DIM)
            self._upd_paso()

        elif self.paso==2:
            self.tmp_it=valor; self.paso=3
            self.lbl_p_it.config(
                text=fmt_carac(valor,dd)+" g",
                fg=GREEN)
            self.lbl_p_ir2.config(
                text="esperando...", fg=YELLOW)
            self._upd_paso()

        elif self.paso==3:
            ir1=self.tmp_ir1; it=self.tmp_it
            ir2=valor
            di=delta_i_carac(ir1, it, ir2)
            self.lbl_p_ir2.config(
                text=fmt_carac(ir2,dd)+" g",
                fg=GREEN)
            self.lbl_di_full.config(
                text=f"ΔI = {fmt_stat_carac(di)} g",
                fg=ACCENT)
            self.lecturas.append(
                {"ir1":ir1,"it":it,"ir2":ir2})
            n=len(self.lecturas)
            self.tbl_ciclo.insert("","end", values=(
                n,
                fmt_carac(ir1,dd),
                fmt_carac(it, dd),
                fmt_carac(ir2,dd),
                fmt_carac(di, min(dd,3))))
            hijos=self.tbl_ciclo.get_children()
            if hijos: self.tbl_ciclo.see(hijos[-1])
            self.lbl_n.config(
                text=f"{n} / {N_LECTURAS_CARAC} lecturas",
                fg=TXT_DIM)
            if n>=2:
                sdi_p=s_delta_carac(self.lecturas)
                self.lbl_sdi.config(
                    text=fmt_stat_carac(sdi_p)+" g",
                    fg=YELLOW)
                deltas=[delta_i_carac(
                    l["ir1"],l["it"],l["ir2"])
                    for l in self.lecturas]
                mn=sum(deltas)/len(deltas)
                var=sum((d-mn)**2 for d in deltas
                        )/(len(deltas)-1)
                self.lbl_var_ciclo.config(
                    text=fmt_stat_carac(var)+" g²")
            self.tmp_ir1=None; self.tmp_it=None
            self.lbl_p_ir1.config(text="—",
                                  fg=TXT_DIM)
            self.lbl_p_it.config(text="—",
                                 fg=TXT_DIM)
            self.lbl_p_ir2.config(text="—",
                                  fg=TXT_DIM)
            if n>=N_LECTURAS_CARAC:
                self._completar()
            else:
                self.paso=1; self._upd_paso()

    def _completar(self):
        self.paso=0
        sdi=s_delta_carac(self.lecturas)
        self.ultimo_sdi=sdi
        deltas=[delta_i_carac(l["ir1"],l["it"],l["ir2"])
                for l in self.lecturas]
        mn=sum(deltas)/len(deltas)
        var=sum((d-mn)**2 for d in deltas
                )/(len(deltas)-1)
        self.lbl_sdi.config(
            text=fmt_stat_carac(sdi)+" g", fg=GREEN)
        self.lbl_var_ciclo.config(
            text=fmt_stat_carac(var)+" g²",
            fg="white", bg=TEAL)
        key=self._key()
        n_sig=len(
            self.hist.get(key,{}).get("ciclos",[]))+1
        self.lbl_n.config(
            text=f"✔  {N_LECTURAS_CARAC}/{N_LECTURAS_CARAC} "
                 f"completo", fg=GREEN)
        self.lbl_paso.config(
            text=f"✔  {ORDINAL_CARAC.get(n_sig,str(n_sig))}"
                 f" ciclo completado\n"
                 f"   s(ΔI) = {fmt_stat_carac(sdi)} g\n"
                 f"   ↓ Presiona '💾 Guardar ciclo'",
            fg=GREEN)
        # Notificar a la app para activar btn guardar
        if self.on_hist_change:
            self.on_hist_change("completado", self)
        hablar(f"{ORDINAL_CARAC.get(n_sig,str(n_sig))} "
               f"ciclo completo")

    def guardar_ciclo(self):
        if self.ultimo_sdi is None: return
        key=self._key()
        ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if key not in self.hist:
            self.hist[key]={"ciclos":[]}
        ciclos=self.hist[key]["ciclos"]
        n_ciclo=len(ciclos)+1
        ciclos.append({
            "n":         n_ciclo,
            "fecha":     ts,
            "sdi":       self.ultimo_sdi,
            "pat_id":    self.e_pat_id.get().strip(),
            "pat_cert":  self.e_pat_cert.get().strip(),
            "pat_fecha": self.e_pat_fecha.get().strip(),
            "lecturas":  [{k:v for k,v in l.items()}
                          for l in self.lecturas],
        })
        guardar_hist_carac(self.hist)
        self._upd_info_pesa()
        self._upd_historial()
        self._upd_grafico()
        total=len(ciclos)
        if total>=N_LECTURAS_CARAC:
            idx=self.combo_pesa.current()
            pesa_lbl=self.cfg["pesas"][idx][1] \
                if 0<=idx<len(self.cfg["pesas"]) \
                else key
            hablar(
                f"Caracterización terminada. "
                f"Pesa {pesa_lbl}. "
                f"{total} ciclos completados.")
            messagebox.showinfo(
                "🎉 Caracterización terminada",
                f"¡Caracterización completada!\n\n"
                f"Pesa: {pesa_lbl}\n"
                f"Ciclos: {total}\n"
                f"s(ΔI) = {fmt_stat_carac(self.ultimo_sdi)} g")
        else:
            hablar(f"Ciclo {n_ciclo} guardado")
            messagebox.showinfo("Guardado",
                f"Ciclo {n_ciclo} guardado.\n"
                f"s(ΔI) = {fmt_stat_carac(self.ultimo_sdi)} g")
        self.ultimo_sdi=None
        if self.on_hist_change:
            self.on_hist_change("guardado", self)

    def _upd_historial(self):
        for i in self.tbl_hist.get_children():
            self.tbl_hist.delete(i)
        key=self._key()
        ciclos=self.hist.get(key,{}).get("ciclos",[])
        sdis=[c["sdi"] for c in ciclos]
        for i,c in enumerate(ciclos):
            var_s="—"
            if i>=1:
                vac=varianza_carac(sdis[:i+1])
                if vac is not None:
                    var_s=fmt_stat_carac(vac)
            self.tbl_hist.insert("","end", values=(
                c["n"],key,c["fecha"],
                c.get("pat_id","—"),
                c.get("pat_cert","—"),
                fmt_stat_carac(c["sdi"]),
                var_s))

    def _upd_grafico(self):
        key=self._key()
        ciclos=self.hist.get(key,{}).get("ciclos",[])
        self._estilo_ax()
        if not ciclos:
            self.ax.text(0.5,0.5,
                "Sin ciclos guardados",
                transform=self.ax.transAxes,
                ha="center",va="center",
                color="#4a6480",fontsize=10)
            self.canvas.draw(); return
        xs=[c["n"] for c in ciclos]
        ys=[c["sdi"] for c in ciclos]
        self.ax.plot(xs,ys,color="#00c8e0",
            linewidth=1.5, marker="o", markersize=5,
            markerfacecolor="#22c55e",
            markeredgecolor="#22c55e")
        if len(ys)>=2:
            media=sum(ys)/len(ys)
            var=varianza_carac(ys)
            sigma=math.sqrt(var) if var else 0
            self.ax.axhline(media,color="#f59e0b",
                linewidth=1,linestyle="--",
                label="media")
            self.ax.axhline(media+sigma,
                color="#ef4444",linewidth=0.8,
                linestyle=":",alpha=0.7,label="+σ")
            self.ax.axhline(media-sigma,
                color="#ef4444",linewidth=0.8,
                linestyle=":",alpha=0.7)
        if xs:
            self.ax.annotate(
                f"{ys[-1]:.6f}",
                (xs[-1],ys[-1]),
                textcoords="offset points",
                xytext=(6,6),fontsize=7,
                color="#00c8e0")
        idx=self.combo_pesa.current()
        pesa_lbl=self.cfg["pesas"][idx][1] \
            if 0<=idx<len(self.cfg["pesas"]) else key
        self.ax.set_title(
            f"s(ΔI) — {self.cfg['nombre']} "
            f"— {pesa_lbl}",
            color="#cdd9e5",fontsize=9,pad=4)
        if len(ys)>=2:
            self.ax.legend(fontsize=7,
                labelcolor="#cdd9e5",
                facecolor="#0a1525",
                edgecolor="#1a2940",
                loc="upper right")
        self.ax.set_xticks(xs)
        self.fig.tight_layout(pad=1.2)
        self.canvas.draw()




class App:
    def __init__(self, root):
        self.root = root
        self.root.title("METROMECANICA — Multi-Balanza v6.0 | ISO/IEC 17025")
        self.root.geometry("1300x840"); self.root.configure(bg=BG)
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.ensayos  = []; self.patrones = cargar_patrones()
        self._build_ui(); self._tick(); self._check_vigencias()
        self.root.after(1500, self._check_alarma_mensual)
        registrar_log("INICIO_SESION", "sistema", "App iniciada")

    def _on_close(self):
        if hasattr(self, 'panel_ambiente'):
            self.panel_ambiente._guardar_config()
            self.panel_ambiente._detener_vigilancia()
        registrar_log('CIERRE_SESION', 'sistema', f'Ensayos realizados: {len(self.ensayos)}')
        if hasattr(self, 'cx_biobase'):    self.cx_biobase.desconectar()
        if hasattr(self, 'cx_radwag'):     self.cx_radwag.desconectar()
        self.root.destroy()

    def _build_tab_registro(self, parent):
        """Pestaña independiente de registro de ensayos ABA."""
        tk.Frame(parent, bg=ACCENT, height=3).pack(fill="x")
        hdr = tk.Frame(parent, bg=PANEL2, padx=16, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="REGISTRO DE ENSAYOS ABA",
                 bg=PANEL2, fg=ACCENT,
                 font=("Georgia", 11, "bold")).pack(side="left")
        self.lbl_cont = tk.Label(hdr, text="Ensayos: 0",
                                  bg=PANEL2, fg=TXT_DIM, font=FN_SM)
        self.lbl_cont.pack(side="right")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # Tabla principal
        frame_t = tk.Frame(parent, bg=BG)
        frame_t.pack(fill="both", expand=True, padx=10, pady=8)

        cols = ("N","Balanza","Timestamp","OT","ID Pesa","Patron",
                "Nominal (g)","Ir1","It","Ir2","Ir_prom",
                "delta_mct (g)","delta_mct (mg)","EMP M2 (mg)","Conforme")
        self.tabla = ttk.Treeview(frame_t, columns=cols, show="headings")

        anchos = [30,90,130,80,80,80,80,80,80,80,80,90,90,90,80]
        for col, w in zip(cols, anchos):
            self.tabla.heading(col, text=col, anchor="center")
            self.tabla.column(col, width=w, anchor="center", minwidth=30)

        sy = ttk.Scrollbar(frame_t, orient="vertical",   command=self.tabla.yview)
        sx = ttk.Scrollbar(frame_t, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True); sx.pack(fill="x")

        # Tag colores conforme/no conforme
        self.tabla.tag_configure("conforme",    background="#1a3a2a",
                                                foreground="#22c55e")
        self.tabla.tag_configure("no_conforme", background="#3a1a1a",
                                                foreground="#ef4444")
        self.tabla.tag_configure("normal",      background="#0f1828",
                                                foreground=TXT)

        # Último ensayo
        self.lbl_ult = tk.Label(parent, text="—",
                                bg=BG, fg=GREEN,
                                font=("Courier New", 8, "bold"),
                                wraplength=900, justify="left")
        self.lbl_ult.pack(anchor="w", padx=10, pady=(0,4))

        # Botones inferiores
        foot = tk.Frame(parent, bg=PANEL2, padx=12, pady=8)
        foot.pack(fill="x")
        tk.Button(foot,
                  text="📄  Generar PDF del ensayo seleccionado",
                  bg=PURPLE, fg="white",
                  font=("Georgia", 9, "bold"),
                  relief="flat", padx=12, pady=5,
                  command=self._pdf_ensayo_seleccionado).pack(side="left", padx=(0,8))
        tk.Button(foot,
                  text="📊  Exportar CSV",
                  bg=ACCENT2, fg="white",
                  font=("Georgia", 9, "bold"),
                  relief="flat", padx=12, pady=5,
                  command=self._exportar).pack(side="left", padx=(0,8))
        tk.Button(foot,
                  text="🗑  Limpiar",
                  bg=PANEL, fg=TXT,
                  font=FN_UI, relief="flat", padx=12, pady=5,
                  command=self._limpiar).pack(side="left")
        tk.Label(foot,
                 text="Coma decimal INACAL  |  δmct = It − (Ir1+Ir2)/2 + δmcr  |  NMP 004:2007",
                 bg=PANEL2, fg=TXT_DIM,
                 font=FN_SM).pack(side="right", padx=8)

    def _build_tab_nmp(self, parent):

        """Pestaña con tabla completa de tolerancias NMP 004:2007 / OIML R111."""
        tk.Frame(parent, bg=YELLOW, height=3).pack(fill="x")
        hdr = tk.Frame(parent, bg=PANEL2, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr,
                 text="TABLA 1 — Errores Máximos Permisibles para Pesas",
                 bg=PANEL2, fg=YELLOW,
                 font=("Georgia", 12, "bold")).pack(side="left")
        tk.Label(hdr,
                 text="  NMP 004:2007 / OIML R111 — Pág. 16 de 129  |  Valores en mg (±δm)",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 9, "italic")).pack(side="left")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # Tabla con todas las clases
        frame_t = tk.Frame(parent, bg=BG)
        frame_t.pack(fill="both", expand=True, padx=16, pady=10)

        cols = ("Valor nominal","E1","E2","F1","F2","M1","M1-2","M2","M2-3","M3")
        tv = ttk.Treeview(frame_t, columns=cols, show="headings")

        anchos = [120,60,60,70,70,80,80,80,80,80]
        for col, w in zip(cols, anchos):
            tv.heading(col, text=col, anchor="center")
            tv.column(col, width=w, anchor="center", minwidth=40)

        # Datos completos NMP 004:2007 Tabla 1
        datos = [
            ("5 000 kg",  "—",     "—",     "25 000","80 000", "250 000","500 000","800 000","1 600 000","2 500 000"),
            ("2 000 kg",  "—",     "—",     "10 000","30 000", "100 000","200 000","300 000","600 000",  "1 000 000"),
            ("1 000 kg",  "—",     "1 600", "5 000", "16 000", "50 000", "100 000","160 000","300 000",  "500 000"),
            ("500 kg",    "—",     "800",   "2 500", "8 000",  "25 000", "50 000", "80 000", "160 000",  "250 000"),
            ("200 kg",    "—",     "300",   "1 000", "3 000",  "10 000", "20 000", "30 000", "60 000",   "100 000"),
            ("100 kg",    "—",     "160",   "500",   "1 600",  "5 000",  "10 000", "16 000", "30 000",   "50 000"),
            ("50 kg",     "25",    "80",    "250",   "800",    "2 500",  "5 000",  "8 000",  "16 000",   "25 000"),
            ("20 kg",     "10",    "30",    "100",   "300",    "1 000",  "—",      "3 000",  "—",        "10 000"),
            ("10 kg",     "5,0",   "16",    "50",    "160",    "500",    "—",      "1 600",  "—",        "5 000"),
            ("5 kg",      "2,5",   "8,0",   "25",    "80",     "250",    "—",      "800",    "—",        "2 500"),
            ("2 kg",      "1,0",   "3,0",   "10",    "30",     "100",    "—",      "300",    "—",        "1 000"),
            ("1 kg",      "0,5",   "1,6",   "5,0",   "16",     "50",     "—",      "160",    "—",        "500"),
            ("500 g",     "0,25",  "0,8",   "2,5",   "8,0",    "25",     "—",      "80",     "—",        "250"),
            ("200 g",     "0,10",  "0,3",   "1,0",   "3,0",    "10",     "—",      "30",     "—",        "100"),
            ("100 g",     "0,05",  "0,16",  "0,5",   "1,6",    "5,0",    "—",      "16",     "—",        "50"),
            ("50 g",      "0,03",  "0,10",  "0,3",   "1,0",    "3,0",    "—",      "10",     "—",        "30"),
            ("20 g",      "0,025", "0,08",  "0,25",  "0,8",    "2,5",    "—",      "8,0",    "—",        "25"),
            ("10 g",      "0,020", "0,06",  "0,20",  "0,6",    "2,0",    "—",      "6,0",    "—",        "20"),
            ("5 g",       "0,016", "0,05",  "0,16",  "0,5",    "1,6",    "—",      "5,0",    "—",        "16"),
            ("2 g",       "0,012", "0,04",  "0,12",  "0,4",    "1,2",    "—",      "4,0",    "—",        "12"),
            ("1 g",       "0,010", "0,03",  "0,10",  "0,3",    "1,0",    "—",      "3,0",    "—",        "10"),
            ("500 mg",    "0,008", "0,025", "0,08",  "0,25",   "0,8",    "—",      "2,5",    "—",        "—"),
            ("200 mg",    "0,006", "0,020", "0,06",  "0,20",   "0,6",    "—",      "2,0",    "—",        "—"),
            ("100 mg",    "0,005", "0,016", "0,05",  "0,16",   "0,5",    "—",      "1,6",    "—",        "—"),
            ("50 mg",     "0,004", "0,012", "0,04",  "0,12",   "0,4",    "—",      "—",      "—",        "—"),
            ("20 mg",     "0,003", "0,010", "0,03",  "0,10",   "0,3",    "—",      "—",      "—",        "—"),
            ("10 mg",     "0,003", "0,008", "0,025", "0,08",   "0,25",   "—",      "—",      "—",        "—"),
            ("5 mg",      "0,003", "0,006", "0,020", "0,06",   "0,20",   "—",      "—",      "—",        "—"),
            ("2 mg",      "0,003", "0,006", "0,020", "0,06",   "0,20",   "—",      "—",      "—",        "—"),
            ("1 mg",      "0,003", "0,006", "0,020", "0,06",   "0,20",   "—",      "—",      "—",        "—"),
        ]

        # Colores por fila — resaltar columna M2
        style = ttk.Style()
        style.configure("NMP.Treeview", rowheight=22,
                        font=("Courier New", 9))
        style.configure("NMP.Treeview.Heading",
                        font=("Georgia", 9, "bold"),
                        background="#1a3a6b",
                        foreground="white")
        tv.configure(style="NMP.Treeview")

        for i, row in enumerate(datos):
            tag = "par" if i % 2 == 0 else "impar"
            # Resaltar filas de pesas de calibración frecuente (1g-25kg)
            if row[0] in ("1 g","2 g","5 g","10 g","20 g","50 g","100 g",
                          "200 g","500 g","1 kg","2 kg","5 kg","10 kg",
                          "20 kg","25 kg","50 kg"):
                tag = "resalt"
            tv.insert("", "end", values=row, tags=(tag,))

        tv.tag_configure("par",    background="#0f1828", foreground=TXT)
        tv.tag_configure("impar",  background="#141f2e", foreground=TXT)
        tv.tag_configure("resalt", background="#1a3a5c", foreground="#00c8e0")

        sb_y = ttk.Scrollbar(frame_t, orient="vertical",   command=tv.yview)
        sb_x = ttk.Scrollbar(frame_t, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        sb_x.pack(fill="x")

        # Pie con nota
        pie = tk.Frame(parent, bg=PANEL2, padx=16, pady=8)
        pie.pack(fill="x")
        tk.Label(pie,
                 text="* Filas resaltadas en azul = valores nominales estándar de calibración  "
                      "| Columna M2 = clase aplicable a pesas patrón de trabajo  "
                      "| Fuente: NMP 004:2007 Tabla 1, pág. 16",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(anchor="w")

    def _build_ui(self):
        tk.Frame(self.root, bg="#8B0000", height=3).pack(fill="x")
        hdr = tk.Frame(self.root, bg=BG, padx=20, pady=8)
        hdr.pack(fill="x")
        # Logo pequeño en header
        if os.path.exists(LOGO_PATH):
            try:
                from PIL import Image as PILImage, ImageTk
                img = PILImage.open(LOGO_PATH).resize((90, 46))
                self._logo_tk = ImageTk.PhotoImage(img)
                tk.Label(hdr, image=self._logo_tk, bg=BG).pack(side="left", padx=(0,10))
            except:
                tk.Label(hdr, text="METROMECANICA", bg=BG, fg="#8B0000",
                         font=("Georgia",14,"bold")).pack(side="left")
        else:
            tk.Label(hdr, text="METROMECANICA", bg=BG, fg="#8B0000",
                     font=("Georgia",14,"bold")).pack(side="left")

        tk.Label(hdr, text="Multi-Balanza v6.0  |  ISO/IEC 17025  |  ABA  |  Monitor Ambiental OIML R111",
                 bg=BG, fg=TXT_DIM, font=("Georgia",8,"italic")).pack(side="left")
        self.lbl_reloj = tk.Label(hdr, bg=BG, fg=TXT_DIM, font=("Courier New",9))
        self.lbl_reloj.pack(side="right")
        tk.Button(hdr, text="Patrones", bg=PANEL2, fg=ACCENT,
                  font=FN_UI, relief="flat", padx=8, pady=2,
                  command=self._abrir_patrones).pack(side="right", padx=8)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        style = ttk.Style(); style.theme_use('default')
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=PANEL2, foreground=TXT_DIM,
                        padding=[16,6], font=('Georgia',9))
        style.map('TNotebook.Tab',
                  background=[('selected', PANEL)],
                  foreground=[('selected', ACCENT)])

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        # Pestañas integradas por balanza
        tab_bio = tk.Frame(nb, bg=BG)
        nb.add(tab_bio, text="  🟢 BIOBASE  ")
        self._build_tab_balanza_integrada(
            tab_bio, "BIOBASE", ACCENT2, "RS-232",
            "5 000 g", "0,01 g", 2, tipo="biobase")

        tab_rad = tk.Frame(nb, bg=BG)
        nb.add(tab_rad, text="  🔵 RADWAG AS  ")
        self._build_tab_balanza_integrada(
            tab_rad, "RADWAG AS", TEAL, "WiFi TCP",
            "220 g", "0,00001 g", 5, tipo="radwag")

        tab_wnt = tk.Frame(nb, bg=BG)
        nb.add(tab_wnt, text="  🟣 WANT GT-30000TR  ")
        self._build_tab_balanza_integrada(
            tab_wnt, "WANT GT-30000TR", "#7c3aed", "Manual",
            "30 000 g", "0,1 g", 1, tipo="want")

        # Pestaña ambiente
        tab_a = tk.Frame(nb, bg=BG)
        nb.add(tab_a, text="  Ambiente / OIML R111  ")
        self.panel_ambiente = PanelAmbiente(tab_a)
        self.panel_ambiente.pack(fill="both", expand=True)
        self.panel_ambiente._app_ref = self

        # Pestaña registro de ensayos
        tab_reg = tk.Frame(nb, bg=BG)
        nb.add(tab_reg, text="  Registro de Ensayos  ")
        self._build_tab_registro(tab_reg)

        # Pestaña tabla tolerancias NMP 004:2007
        tab_nmp = tk.Frame(nb, bg=BG)
        nb.add(tab_nmp, text="  Tabla NMP 004:2007  ")
        self._build_tab_nmp(tab_nmp)

        # Pestaña Incertidumbre GUM
        tab_gum = tk.Frame(nb, bg=BG)
        nb.add(tab_gum, text="  Incertidumbre GUM  ")
        self.panel_gum = PanelGUM(tab_gum, self)
        self.panel_gum.pack(fill="both", expand=True)

    def _build_tab_balanza_integrada(self, parent, bal_name, color,
                                      cx_tipo, capacidad, division,
                                      decimales, tipo="biobase"):
        """Pestaña completa por balanza: header + sub-notebook ABA + Caracterización"""
        tk.Frame(parent, bg=color, height=4).pack(fill="x")
        hdr = tk.Frame(parent, bg=PANEL2, padx=12, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text=bal_name, bg=PANEL2, fg=color,
                 font=("Georgia", 12, "bold")).pack(side="left")
        tk.Label(hdr, text=f"  {cx_tipo}  ·  Cap: {capacidad}  ·  d: {division}",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 8, "italic")).pack(side="left")

        # Header condiciones — 2 filas compactas
        cond = tk.Frame(parent, bg=PANEL2, padx=10, pady=4)
        cond.pack(fill="x")
        tk.Frame(cond, bg=YELLOW, height=2).pack(fill="x", pady=(0, 4))
        fila1 = tk.Frame(cond, bg=PANEL2); fila1.pack(fill="x")

        tk.Label(fila1, text="OT:", bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left", padx=(0,2))
        if not hasattr(self, 'ot_aba_var'):
            self.ot_aba_var = tk.StringVar()
        tk.Entry(fila1, textvariable=self.ot_aba_var, width=10,
                 font=("Courier New",8), bg=PANEL, fg=ACCENT,
                 insertbackground=ACCENT, relief="flat", bd=2).pack(side="left", padx=(0,8))

        tk.Label(fila1, text="Operador:", bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left", padx=(0,2))
        if not hasattr(self, 'op_aba_var'):
            self.op_aba_var = tk.StringVar()
        if not hasattr(self, 'combo_op_aba'):
            self.combo_op_aba = ttk.Combobox(fila1, textvariable=self.op_aba_var,
                                              values=cargar_operadores(), width=12,
                                              font=("Courier New",8))
            self.combo_op_aba.pack(side="left", padx=(0,2))
        else:
            ttk.Combobox(fila1, textvariable=self.op_aba_var,
                         values=cargar_operadores(), width=12,
                         font=("Courier New",8)).pack(side="left", padx=(0,2))
        tk.Button(fila1, text="+", bg=ACCENT2, fg="white",
                  font=("Georgia",8,"bold"), relief="flat", padx=4, pady=0,
                  command=self._agregar_operador_aba).pack(side="left", padx=(0,8))

        tk.Label(fila1, text="Pesa:", bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left", padx=(0,2))
        if not hasattr(self, 'inst_aba_var'):
            self.inst_aba_var = tk.StringVar()
        ttk.Combobox(fila1, textvariable=self.inst_aba_var, width=8,
                     font=("Courier New",8),
                     values=["1 g","2 g","5 g","10 g","20 g","50 g","100 g",
                             "200 g","500 g","1 kg","2 kg","5 kg","10 kg",
                             "20 kg","25 kg"]).pack(side="left", padx=(0,8))

        tk.Label(fila1, text="RUC:", bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left", padx=(0,2))
        if not hasattr(self, 'ruc_aba_var'):
            self.ruc_aba_var = tk.StringVar()
        tk.Entry(fila1, textvariable=self.ruc_aba_var, width=12,
                 font=("Courier New",8), bg=PANEL, fg=TXT,
                 insertbackground=ACCENT, relief="flat", bd=2).pack(side="left", padx=(0,2))
        tk.Button(fila1, text="🔍", bg=PANEL2, fg=ACCENT,
                  font=("Georgia",9), relief="flat", padx=3,
                  command=self._consultar_ruc_aba).pack(side="left", padx=(0,8))

        tk.Button(fila1, text="⬆ INICIO", bg="#1a4731", fg=GREEN,
                  font=("Georgia",8,"bold"), relief="flat", padx=8, pady=3,
                  command=self._reg_inicio_aba).pack(side="left", padx=(0,4))
        tk.Button(fila1, text="⬇ FIN", bg="#7c2d12", fg=ORANGE,
                  font=("Georgia",8,"bold"), relief="flat", padx=8, pady=3,
                  command=self._reg_fin_aba).pack(side="left", padx=(0,8))

        if not hasattr(self, 'lbl_oiml_aba'):
            self.lbl_oiml_aba = tk.Label(fila1, text="• Sin registros",
                                         bg=PANEL2, fg=TXT_DIM,
                                         font=("Courier New",7,"bold"))
            self.lbl_oiml_aba.pack(side="right")

        fila2 = tk.Frame(cond, bg=PANEL2); fila2.pack(fill="x", pady=(2,0))
        if not hasattr(self, 'lbl_ini_aba'):
            self.lbl_ini_aba = tk.Label(fila2, text="INICIO: no registrado",
                                        bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
            self.lbl_ini_aba.pack(side="left", padx=(0,10))
            self.lbl_fin_aba = tk.Label(fila2, text="FIN: no registrado",
                                        bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
            self.lbl_fin_aba.pack(side="left", padx=(0,10))
            self.lbl_rho_aba = tk.Label(fila2, text="rho: —",
                                        bg=PANEL2, fg=TEAL, font=("Courier New",7))
            self.lbl_rho_aba.pack(side="left", padx=(0,8))
            self.lbl_emp_aba = tk.Label(fila2, text="Empuje: —",
                                        bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
            self.lbl_emp_aba.pack(side="left", padx=(0,8))
            self.lbl_var_aba = tk.Label(fila2, text="",
                                        bg=PANEL2, fg=TXT_DIM, font=("Courier New",7))
            self.lbl_var_aba.pack(side="left")
            self.lbl_razon_aba = tk.Label(fila2, text="",
                                           bg=PANEL2, fg=GREEN, font=("Courier New",7))
            self.lbl_razon_aba.pack(side="right", padx=4)
            self.dir_fiscal_var = tk.StringVar(value="")
            self.lbl_dir_aba = tk.Label(fila2, text="", bg=PANEL2,
                                        fg="#94a3b8", font=("Courier New",7))
            self.lbl_dir_aba.pack(side="right", padx=4)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # Sub-notebook: ABA | Caracterización
        subnb = ttk.Notebook(parent)
        subnb.pack(fill="both", expand=True, padx=4, pady=4)

        tab_aba = tk.Frame(subnb, bg=BG)
        subnb.add(tab_aba, text="  Procedimiento ABA  ")

        if tipo == "biobase":
            self._panel_cx_biobase(tab_aba)
            self.panel_bio = PanelBalanza(tab_aba, "BIOBASE", ACCENT2,
                                          capacidad, division, decimales,
                                          self.patrones)
            self.panel_bio.pack(fill="both", expand=True)
            self.panel_bio.on_aba_completo = self._registrar_aba
            self.cx_biobase = ConexionBiobase(self.panel_bio)
        elif tipo == "radwag":
            self._panel_cx_radwag(tab_aba)
            self.panel_rad = PanelBalanza(tab_aba, "RADWAG AS", TEAL,
                                          capacidad, division, decimales,
                                          self.patrones)
            self.panel_rad.pack(fill="both", expand=True)
            self.panel_rad.on_aba_completo = self._registrar_aba
            self.cx_radwag = ConexionRadwag(self.panel_rad)
        else:
            self.panel_want = PanelWANT(tab_aba, self.patrones)
            self.panel_want.pack(fill="both", expand=True)
            self.panel_want.on_aba_completo = self._registrar_aba

        tab_caract = tk.Frame(subnb, bg=BG)
        subnb.add(tab_caract, text="  ⚙ Caracterización PC-008  ")
        self._build_tab_config(tab_caract, bal_name, color)

    def _build_tab_config(self, parent, bal_name, color):
        """
        Caracterización real por pesa usando PanelCarac (PC-008 §10.2)
        10 lecturas ABA en vivo: Ir1 → It → Ir2
        s(ΔI), varianza entre ciclos, historial, gráfico matplotlib
        """
        import math

        # Config por balanza
        _CFGS = {
            "BIOBASE": {
                "nombre":          "BIOBASE",
                "color":           ACCENT2,
                "tipo":            "serial",
                "pesas":           PESAS_BIOBASE,
                "decimales_display": 2,
                "puerto":          "COM6",
                "baud":            9600,
            },
            "RADWAG AS": {
                "nombre":          "RADWAG AS",
                "color":           TEAL,
                "tipo":            "wifi",
                "pesas":           PESAS_RADWAG,
                "decimales_display": 4,
                "ip":              "192.168.18.65",
                "port":            4001,
            },
            "WANT GT-30000TR": {
                "nombre":          "WANT GT-30000TR",
                "color":           "#7c3aed",
                "tipo":            "manual",
                "pesas":           PESAS_WANT,
                "decimales_display": 1,
            },
        }
        cfg = _CFGS.get(bal_name, _CFGS["BIOBASE"])

        # Historial compartido
        if not hasattr(self, "_hist_carac"):
            self._hist_carac = cargar_hist_carac()

        def on_hist_change(evento, panel):
            if evento == "completado":
                self._btn_guardar_carac = panel

        # Header
        tk.Frame(parent, bg=color, height=4).pack(fill="x")
        hdr = tk.Frame(parent, bg=PANEL2, padx=12, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"CARACTERIZACION — {bal_name}",
                 bg=PANEL2, fg=color,
                 font=("Georgia",11,"bold")).pack(side="left")
        tk.Label(hdr,
                 text="  PC-008 §10.2  10 lecturas ABA  s(dI)  Varianza  Historial",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia",8,"italic")).pack(side="left")

        # Botón guardar ciclo
        btn_grd = tk.Button(hdr, text="Guardar ciclo",
                            bg=GREEN, fg="white",
                            font=("Georgia",9,"bold"),
                            relief="flat", padx=12, pady=4,
                            state="disabled")
        btn_grd.pack(side="right", padx=(8,0))

        def _guardar():
            if hasattr(self, "_btn_guardar_carac"):
                self._btn_guardar_carac.guardar_ciclo()
                btn_grd.config(state="disabled",
                               text="Guardar ciclo")

        btn_grd.config(command=_guardar)

        def on_change_ext(evento, panel):
            on_hist_change(evento, panel)
            if evento == "completado":
                btn_grd.config(state="normal",
                               text="GUARDAR CICLO — PRESIONA AQUI")
            elif evento == "guardado":
                btn_grd.config(state="disabled",
                               text="Guardar ciclo")

        # Panel de caracterización
        panel_c = PanelCarac(parent, cfg,
                             self._hist_carac,
                             on_hist_change=on_change_ext)
        panel_c.pack(fill="both", expand=True)


    def _build_tab_balanzas(self, parent):
        # ── Panel superior: Condiciones ambientales compartido ──────────
        self._panel_condiciones_aba(parent)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        col1 = tk.Frame(body, bg=BG)
        col1.pack(side="left", fill="both", expand=True, padx=(0,4))
        self._panel_cx_biobase(col1)
        self.panel_bio = PanelBalanza(col1, "BIOBASE", ACCENT2,
                                      "5 000 g", "0,01 g", 2, self.patrones)
        self.panel_bio.pack(fill="both", expand=True)
        self.panel_bio.on_aba_completo = self._registrar_aba
        self.cx_biobase = ConexionBiobase(self.panel_bio)

        col2 = tk.Frame(body, bg=BG)
        col2.pack(side="left", fill="both", expand=True, padx=4)
        self._panel_cx_radwag(col2)
        self.panel_rad = PanelBalanza(col2, "RADWAG AS", TEAL,
                                      "220 g", "0,00001 g", 5, self.patrones)
        self.panel_rad.pack(fill="both", expand=True)
        self.panel_rad.on_aba_completo = self._registrar_aba
        self.cx_radwag = ConexionRadwag(self.panel_rad)

        # ── WANT GT-30000TR — ingreso manual ─────────────────────────
        col_want = tk.Frame(body, bg=BG)
        col_want.pack(side="left", fill="both", expand=True, padx=4)
        self.panel_want = PanelWANT(col_want, self.patrones)
        self.panel_want.pack(fill="both", expand=True)
        self.panel_want.on_aba_completo = self._registrar_aba

        # Registro movido a pestaña independiente

        # Botones de registro están en la pestaña Registro de Ensayos

        # Botones de registro están en la pestaña Registro de Ensayos

    def _panel_condiciones_aba(self, parent):
        """Panel superior compartido — datos de calibración + condiciones ambientales."""
        p = tk.Frame(parent, bg=PANEL2, padx=12, pady=7)
        p.pack(fill="x")
        tk.Frame(p, bg=YELLOW, height=2).pack(fill="x", pady=(0,5))

        # ── Fila superior: Datos de calibración ────────────────
        fila_datos = tk.Frame(p, bg=PANEL2)
        fila_datos.pack(fill="x", pady=(0,4))

        # OT
        tk.Label(fila_datos, text="OT:",
                 bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left")
        self.ot_aba_var = tk.StringVar()
        tk.Entry(fila_datos, textvariable=self.ot_aba_var,
                 width=12, font=("Courier New", 8),
                 bg=PANEL, fg=ACCENT, insertbackground=ACCENT,
                 relief="flat", bd=2).pack(side="left", padx=(2,10))

        # Operador
        tk.Label(fila_datos, text="Operador:",
                 bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left")
        self.op_aba_var = tk.StringVar()
        ops = cargar_operadores()
        self.combo_op_aba = ttk.Combobox(fila_datos, textvariable=self.op_aba_var,
                                          values=ops, width=14,
                                          font=("Courier New", 8))
        self.combo_op_aba.pack(side="left", padx=(2,2))
        tk.Button(fila_datos, text="+",
                  bg=ACCENT2, fg="white",
                  font=("Georgia", 9, "bold"),
                  relief="flat", padx=5, pady=0,
                  command=self._agregar_operador_aba).pack(side="left", padx=(0,10))

        # Instrumento — lista NMP 004:2007
        tk.Label(fila_datos, text="Pesa (nominal):",
                 bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left")
        self.inst_aba_var = tk.StringVar()
        pesas_nmp = ["1 g","2 g","5 g","10 g","20 g","50 g","100 g","200 g","500 g",
                     "1 kg","2 kg","5 kg","10 kg","20 kg","25 kg"]
        ttk.Combobox(fila_datos, textvariable=self.inst_aba_var,
                     values=pesas_nmp, width=10,
                     font=("Courier New", 8)).pack(side="left", padx=(2,10))

        # RUC
        tk.Label(fila_datos, text="RUC:",
                 bg=PANEL2, fg=TXT, font=FN_SM).pack(side="left")
        self.ruc_aba_var = tk.StringVar()
        tk.Entry(fila_datos, textvariable=self.ruc_aba_var,
                 width=12, font=("Courier New", 8),
                 bg=PANEL, fg=TXT, insertbackground=ACCENT,
                 relief="flat", bd=2).pack(side="left", padx=2)
        tk.Button(fila_datos, text="🔍",
                  bg=PANEL2, fg=ACCENT,
                  font=("Georgia", 9), relief="flat", padx=4,
                  command=self._consultar_ruc_aba).pack(side="left", padx=2)
        self.lbl_razon_aba = tk.Label(fila_datos, text="",
                                       bg=PANEL2, fg=GREEN,
                                       font=("Courier New", 7))
        self.lbl_razon_aba.pack(side="left", padx=6)
        self.dir_fiscal_var = tk.StringVar(value="")
        fila_dir = tk.Frame(p, bg=PANEL2); fila_dir.pack(fill="x", pady=(0,2))
        self.lbl_dir_aba = tk.Label(fila_dir, text="", bg=PANEL2, fg="#94a3b8",
                                    font=("Courier New",7), anchor="w")
        self.lbl_dir_aba.pack(side="left", padx=(6,0))

        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(2,5))

        # ── Fila: título condiciones + estado OIML ─────────────
        hdr = tk.Frame(p, bg=PANEL2)
        hdr.pack(fill="x")
        tk.Label(hdr,
                 text="CONDICIONES AMBIENTALES DEL ENSAYO",
                 bg=PANEL2, fg=YELLOW,
                 font=("Georgia", 9, "bold")).pack(side="left")
        tk.Label(hdr,
                 text="  T, HR y P ingresados manualmente — Hora automática — "
                      "Valores corregidos por trazabilidad (Lagrange)",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia", 7, "italic")).pack(side="left")
        self.lbl_oiml_aba = tk.Label(hdr,
                                      text="● Sin registros",
                                      bg=PANEL2, fg=TXT_DIM,
                                      font=("Courier New", 8, "bold"))
        self.lbl_oiml_aba.pack(side="right")

        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(4,6))

        # ── Fila: INICIO | FIN | densidad ──────────────────────
        fila = tk.Frame(p, bg=PANEL2)
        fila.pack(fill="x")

        blk_i = tk.Frame(fila, bg=PANEL2)
        blk_i.pack(side="left", padx=(0,10))
        tk.Button(blk_i, text="📍  Registrar INICIO",
                  bg=TEAL, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=10, pady=4,
                  command=self._reg_inicio_aba).pack(anchor="w")
        self.lbl_ini_aba = tk.Label(blk_i,
                                     text="INICIO: no registrado",
                                     bg=PANEL2, fg=TXT_DIM,
                                     font=("Courier New", 8),
                                     justify="left")
        self.lbl_ini_aba.pack(anchor="w", pady=(3,0))

        tk.Frame(fila, bg=BORDER, width=1).pack(side="left", fill="y", padx=10)

        blk_f = tk.Frame(fila, bg=PANEL2)
        blk_f.pack(side="left", padx=(0,10))
        tk.Button(blk_f, text="📍  Registrar FIN",
                  bg=ORANGE, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=10, pady=4,
                  command=self._reg_fin_aba).pack(anchor="w")
        self.lbl_fin_aba = tk.Label(blk_f,
                                     text="FIN: no registrado",
                                     bg=PANEL2, fg=TXT_DIM,
                                     font=("Courier New", 8),
                                     justify="left")
        self.lbl_fin_aba.pack(anchor="w", pady=(3,0))

        tk.Frame(fila, bg=BORDER, width=1).pack(side="left", fill="y", padx=10)

        blk_d = tk.Frame(fila, bg=PANEL2)
        blk_d.pack(side="left", padx=(0,6))
        self.lbl_rho_aba = tk.Label(blk_d, text="rho: —",
                                     bg=PANEL2, fg=TEAL,
                                     font=("Courier New", 9, "bold"))
        self.lbl_rho_aba.pack(anchor="w")
        self.lbl_emp_aba = tk.Label(blk_d, text="Empuje: —",
                                     bg=PANEL2, fg=TXT_DIM,
                                     font=("Georgia", 7, "bold"))
        self.lbl_emp_aba.pack(anchor="w")
        self.lbl_var_aba = tk.Label(blk_d, text="ΔT ini→fin: —",
                                     bg=PANEL2, fg=TXT_DIM,
                                     font=("Courier New", 7))
        self.lbl_var_aba.pack(anchor="w")

    def _agregar_operador_aba(self):
        """Agrega un nuevo operador capacitado a la lista."""
        win = tk.Toplevel(self.root)
        win.title("Agregar Operador")
        win.geometry("340x160"); win.configure(bg=PANEL)
        win.grab_set()
        tk.Frame(win, bg=ACCENT2, height=3).pack(fill="x")
        tk.Label(win, text="Nuevo operador capacitado:",
                 bg=PANEL, fg=TXT,
                 font=("Georgia", 9, "bold")).pack(pady=(12,6))
        var = tk.StringVar()
        e = tk.Entry(win, textvariable=var, width=28,
                     font=("Courier New", 10),
                     bg=PANEL2, fg=TXT,
                     insertbackground=ACCENT2,
                     relief="flat", bd=3)
        e.pack(padx=20); e.focus_set()
        def confirmar():
            nombre = var.get().strip()
            if not nombre:
                messagebox.showwarning("Campo vacío",
                    "Ingresa el nombre del operador.", parent=win)
                return
            ops = cargar_operadores()
            if nombre not in ops:
                ops.append(nombre)
                guardar_operadores(ops)
            # Actualizar todos los combos de operador
            if hasattr(self, 'combo_op_aba'):
                self.combo_op_aba['values'] = ops
            if hasattr(self, 'panel_ambiente') and hasattr(self.panel_ambiente, 'combo_op'):
                self.panel_ambiente.combo_op['values'] = ops
            self.op_aba_var.set(nombre)
            win.destroy()
            messagebox.showinfo("✓ Operador agregado",
                f"'{nombre}' agregado a la lista de operadores.")
        tk.Button(win, text="✓  Confirmar",
                  bg=ACCENT2, fg="white",
                  font=("Georgia", 9, "bold"),
                  relief="flat", padx=16, pady=5,
                  command=confirmar).pack(pady=10)
        win.bind('<Return>', lambda e: confirmar())

    def _consultar_ruc_aba(self):
        """Consulta RUC en SUNAT via apiperu.dev (gratuita)."""
        ruc = self.ruc_aba_var.get().strip()
        if len(ruc) != 11 or not ruc.isdigit():
            messagebox.showwarning("RUC inválido",
                "El RUC debe tener exactamente 11 dígitos.")
            return
        self.lbl_razon_aba.config(text="Consultando SUNAT...", fg=YELLOW)
        self.root.update_idletasks()
        import threading
        def consultar():
            razon, estado = None, None
            # Intentar múltiples APIs gratuitas
            apis = [
                f"https://apiperu.dev/api/ruc/{ruc}",
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
            ]
            for url in apis:
                try:
                    import urllib.request, json
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Metromecanica-Lab/1.0',
                        'Accept': 'application/json'})
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = json.loads(resp.read().decode())
                    # apiperu.dev retorna data.data o data directamente
                    d = data.get('data', data)
                    razon  = (d.get('razon_social') or d.get('razonSocial')
                              or d.get('nombre') or '—')
                    estado = (d.get('estado') or d.get('condicion') or '')
                    dir_parts=[]
                    for campo in ('direccion','domicilio_fiscal','domicilio'):
                        v=d.get(campo,'').strip()
                        if v: dir_parts.append(v); break
                    for campo in ('distrito','provincia','departamento'):
                        v=d.get(campo,'').strip()
                        if v: dir_parts.append(v)
                    direccion=', '.join(dir_parts) if dir_parts else ''
                    if razon and razon != '—':
                        break
                except:
                    continue

            def actualizar(r, e, direc=''):
                if r:
                    txt = f"{r}  [{e}]" if e else r
                    col = GREEN if 'ACTIVO' in (e or '').upper() else YELLOW
                else:
                    txt="Sin conexión — ingresa razón social manualmente"
                    col=TXT_DIM; direc=''
                self.lbl_razon_aba.config(text=txt, fg=col)
                if hasattr(self,'lbl_dir_aba') and self.lbl_dir_aba.winfo_exists():
                    self.lbl_dir_aba.config(text=f"📍 {direc}" if direc else '',fg="#94a3b8")
                if hasattr(self,'dir_fiscal_var'):
                    self.dir_fiscal_var.set(direc)
                if hasattr(self,'panel_ambiente'):
                    self.panel_ambiente.ruc_var.set(ruc)
                    if hasattr(self.panel_ambiente,'lbl_razon'):
                        self.panel_ambiente.lbl_razon.config(text=txt,fg=col)
            self.root.after(0, actualizar, razon, estado, direccion)
        threading.Thread(target=consultar, daemon=True).start()

    def _reg_inicio_aba(self):
        """Registra condición INICIO desde la pestaña ABA — sincroniza datos."""
        if not hasattr(self, 'panel_ambiente'):
            return
        self.panel_ambiente._app_ref = self
        # Sincronizar OT, operador, instrumento, RUC hacia panel_ambiente
        if hasattr(self, 'ot_aba_var'):
            self.panel_ambiente.ot_var.set(self.ot_aba_var.get())
        if hasattr(self, 'op_aba_var'):
            self.panel_ambiente.operador_var.set(self.op_aba_var.get())
        if hasattr(self, 'inst_aba_var'):
            self.panel_ambiente.instrumento_var.set(self.inst_aba_var.get())
        if hasattr(self, 'ruc_aba_var'):
            self.panel_ambiente.ruc_var.set(self.ruc_aba_var.get())
        self.panel_ambiente._registrar_inicio()

    def _reg_fin_aba(self):
        """Registra condición FIN desde la pestaña ABA — sincroniza datos."""
        if not hasattr(self, 'panel_ambiente'):
            return
        self.panel_ambiente._app_ref = self
        if hasattr(self, 'ot_aba_var'):
            self.panel_ambiente.ot_var.set(self.ot_aba_var.get())
        if hasattr(self, 'op_aba_var'):
            self.panel_ambiente.operador_var.set(self.op_aba_var.get())
        if hasattr(self, 'inst_aba_var'):
            self.panel_ambiente.instrumento_var.set(self.inst_aba_var.get())
        if hasattr(self, 'ruc_aba_var'):
            self.panel_ambiente.ruc_var.set(self.ruc_aba_var.get())
        self.panel_ambiente._registrar_fin()



    def _actualizar_panel_cond_aba(self):
        """Sincroniza el panel de condiciones de la pestaña ABA."""
        if not hasattr(self, 'panel_ambiente'):
            return
        pa = self.panel_ambiente
        ci = pa.cond_inicio
        cf = pa.cond_fin

        def fmt_cond(d, label, color):
            if not d:
                return f"{label}: no registrado", TXT_DIM
            c = d.get('corr', {})
            t = c.get('t_corr', d.get('temp', 0)) if c else d.get('temp', 0)
            h = c.get('h_corr', d.get('hr',   0)) if c else d.get('hr',   0)
            p = c.get('p_corr', d.get('presion',0)) if c else d.get('presion',0)
            txt = (f"{label} ({d.get('hora','—')}):  "
                   f"T={t:.4f}°C  HR={h:.2f}%  P={p:.2f} mbar"
                   ).replace(".",",")
            return txt, color

        txt_i, col_i = fmt_cond(ci, "INICIO", TEAL)
        txt_f, col_f = fmt_cond(cf, "FIN",    ORANGE)
        self.lbl_ini_aba.config(text=txt_i, fg=col_i)
        self.lbl_fin_aba.config(text=txt_f, fg=col_f)

        # Densidad promedio
        if ci and cf:
            def tc(d):
                c = d.get('corr',{})
                return c.get('t_corr', d['temp']) if c else d['temp']
            def hc(d):
                c = d.get('corr',{})
                return c.get('h_corr', d['hr']) if c else d['hr']
            def pc(d):
                c = d.get('corr',{})
                return c.get('p_corr', d['presion']) if c else d['presion']

            t_prom = (tc(ci) + tc(cf)) / 2
            h_prom = (hc(ci) + hc(cf)) / 2
            p_prom = (pc(ci) + pc(cf)) / 2
            delta_t = abs(tc(cf) - tc(ci))

            rho = calcular_densidad_aire(t_prom, h_prom, p_prom)
            desp, desv = evaluar_empuje_aire(rho)

            self.lbl_rho_aba.config(
                text=f"rho: {str(rho).replace('.',',')} kg/m3  (CIPM-2007)",
                fg=TEAL)
            self.lbl_emp_aba.config(
                text=(f"Empuje: {str(desv).replace('.',',')}%  DESPRECIABLE"
                      if desp else
                      f"Empuje: {str(desv).replace('.',',')}%  NO DESPRECIABLE"),
                fg=GREEN if desp else RED)
            v1_ok = delta_t <= VAR_MAX_1H
            self.lbl_var_aba.config(
                text=f"ΔT ini→fin: {str(round(delta_t,4)).replace('.',',')}°C  "
                     f"(lim ±{VAR_MAX_1H})  {'✓' if v1_ok else '⚠'}",
                fg=GREEN if v1_ok else RED)

            # Estado OIML rápido
            t_i_ok = TEMP_MIN <= tc(ci) <= TEMP_MAX
            t_f_ok = TEMP_MIN <= tc(cf) <= TEMP_MAX
            h_i_ok = hc(ci) <= HR_MAX
            h_f_ok = hc(cf) <= HR_MAX
            ok = t_i_ok and t_f_ok and h_i_ok and h_f_ok and v1_ok
            self.lbl_oiml_aba.config(
                text="✓ CONFORME — OIML R111 M2" if ok else "⚠ NO CONFORME",
                fg=GREEN if ok else RED)
        elif ci:
            self.lbl_oiml_aba.config(
                text="● INICIO registrado — falta FIN",
                fg=YELLOW)

    def _panel_cx_biobase(self, parent):
        p = tk.Frame(parent, bg=PANEL2, padx=10, pady=5)
        p.pack(fill="x", pady=(0,4))
        tk.Label(p, text="BIOBASE RS-232", bg=PANEL2, fg=ACCENT2,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(2,4))
        row = tk.Frame(p, bg=PANEL2); row.pack(fill="x")
        tk.Label(row, text="Puerto:", bg=PANEL2, fg=TXT, font=FN_UI).pack(side="left")
        self.combo_bio_port = ttk.Combobox(row, width=7, state="readonly")
        puertos = [x.device for x in serial.tools.list_ports.comports()]
        self.combo_bio_port["values"] = puertos
        self.combo_bio_port.set("COM6" if "COM6" in puertos else (puertos[0] if puertos else ""))
        self.combo_bio_port.pack(side="left", padx=4)
        tk.Label(row, text="Baud:", bg=PANEL2, fg=TXT, font=FN_UI).pack(side="left")
        self.combo_bio_baud = ttk.Combobox(row, width=6, state="readonly",
                                           values=["2400","4800","9600","19200"])
        self.combo_bio_baud.set("9600"); self.combo_bio_baud.pack(side="left", padx=4)
        self.btn_bio = tk.Button(row, text="Conectar", bg=ACCENT2, fg="white",
                                 font=("Georgia",8,"bold"), relief="flat",
                                 padx=8, pady=2, command=self._toggle_bio)
        self.btn_bio.pack(side="left", padx=4)
        tk.Button(row, text="R", bg=PANEL2, fg=TXT_DIM, font=("Georgia",10),
                  relief="flat", command=self._refresh_ports).pack(side="left")

    def _panel_cx_radwag(self, parent):
        p = tk.Frame(parent, bg=PANEL2, padx=10, pady=5)
        p.pack(fill="x", pady=(0,4))
        tk.Label(p, text="RADWAG AS WiFi TCP", bg=PANEL2, fg=TEAL,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(2,4))
        row = tk.Frame(p, bg=PANEL2); row.pack(fill="x")
        tk.Label(row, text="IP:", bg=PANEL2, fg=TXT, font=FN_UI).pack(side="left")
        self.e_ip = tk.Entry(row, width=14, font=("Courier New",9),
                             bg=PANEL, fg=TXT, insertbackground=TEAL,
                             relief="flat", bd=2)
        self.e_ip.insert(0, RADWAG_IP); self.e_ip.pack(side="left", padx=4)
        tk.Label(row, text="Puerto:", bg=PANEL2, fg=TXT, font=FN_UI).pack(side="left")
        self.e_port = tk.Entry(row, width=5, font=("Courier New",9),
                               bg=PANEL, fg=TXT, insertbackground=TEAL,
                               relief="flat", bd=2)
        self.e_port.insert(0, str(RADWAG_PORT)); self.e_port.pack(side="left", padx=4)
        self.btn_rad = tk.Button(row, text="Conectar", bg=TEAL, fg="white",
                                 font=("Georgia",8,"bold"), relief="flat",
                                 padx=8, pady=2, command=self._toggle_rad)
        self.btn_rad.pack(side="left", padx=4)
        tk.Button(row, text="SI", bg=PANEL2, fg=TEAL,
                  font=("Courier New",8,"bold"), relief="flat",
                  padx=5, pady=2,
                  command=lambda: self.cx_radwag.solicitar_lectura()).pack(
                      side="left", padx=2)

    def _panel_registro(self, parent):
        outer = tk.Frame(parent, bg=BORDER); outer.pack(fill="both", expand=True)
        tk.Frame(outer, bg=ACCENT, width=3).pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=PANEL, padx=8, pady=8)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text="REGISTRO DE ENSAYOS ABA",
                 bg=PANEL, fg=ACCENT, font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(2,6))
        cols = ("N","Balanza","Timestamp","ID Pesa","Patron","Ir1","It","Ir2","Ir_prom","delta_mct")
        self.tabla = ttk.Treeview(inner, columns=cols, show="headings")
        for col, w in zip(cols, [28,70,120,80,70,72,72,72,78,72]):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=w, anchor="center", minwidth=28)
        sy = ttk.Scrollbar(inner, orient="vertical", command=self.tabla.yview)
        sx = ttk.Scrollbar(inner, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True); sx.pack(fill="x")
        self.lbl_ult = tk.Label(inner, text="—", bg=PANEL, fg=GREEN,
                                font=("Courier New",8,"bold"),
                                wraplength=290, justify="left")
        self.lbl_ult.pack(anchor="w", pady=(5,0))
        # Botón PDF — actúa sobre la fila seleccionada (o último ensayo)
        tk.Button(inner,
                  text="📄  Generar PDF del ensayo seleccionado",
                  bg=PURPLE, fg="white",
                  font=("Georgia", 8, "bold"),
                  relief="flat", padx=8, pady=5,
                  command=self._pdf_ensayo_seleccionado).pack(fill="x", pady=(6,0))

    def _pdf_ensayo_seleccionado(self):
        """Genera PDF del ensayo seleccionado en la tabla, o del último si no hay selección."""
        if not self.ensayos:
            messagebox.showinfo("Sin ensayos", "No hay ensayos registrados.")
            return
        # Obtener ensayo seleccionado o último
        sel = self.tabla.selection()
        if sel:
            idx = self.tabla.index(sel[0])
            ensayo = self.ensayos[idx]
        else:
            ensayo = self.ensayos[-1]

        # Verificar campos obligatorios
        alertas = []
        ot = ensayo.get('ot', '').strip()
        ruc = ensayo.get('ruc', '').strip()
        id_pesa = ensayo.get('id_pesa', '').strip()
        if not ot or ot == '—':
            alertas.append("• N° de OT / Referencia")
        if not ruc or ruc == '—':
            alertas.append("• RUC del cliente")
        if not id_pesa or id_pesa in ('—', 'pesa'):
            alertas.append("• Identificación de la pesa (ID pesa)")
        if alertas:
            continuar = messagebox.askyesno(
                "⚠  Datos incompletos",
                "Faltan los siguientes datos en el ensayo:\n\n"
                + "\n".join(alertas) +
                "\n\n¿Deseas generar el PDF de todas formas?\n"
                "(El documento quedará con campos vacíos)",
                icon="warning")
            if not continuar:
                return

        # Verificar condición FIN
        cond_fin = {}
        if hasattr(self, 'panel_ambiente'):
            cond_fin = self.panel_ambiente.cond_fin
        if not cond_fin:
            messagebox.showerror(
                "⛔  Condiciones ambientales FINALES requeridas",
                "No se puede generar el PDF.\n\n"
                "Debes registrar las condiciones ambientales FINALES\n"
                "antes de generar el informe.\n\n"
                "→ Presiona  📍 Registrar FIN  en el panel superior.")
            return
        self._generar_pdf_ensayo(ensayo)

    def _tick(self):
        self.lbl_reloj.config(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(1000, self._tick)

    def _refresh_ports(self):
        puertos = [x.device for x in serial.tools.list_ports.comports()]
        self.combo_bio_port["values"] = puertos

    def _toggle_bio(self):
        if self.cx_biobase.activo:
            self.cx_biobase.desconectar(); self.btn_bio.config(text="Conectar", bg=ACCENT2)
        else:
            if self.cx_biobase.conectar(self.combo_bio_port.get(), int(self.combo_bio_baud.get())):
                self.btn_bio.config(text="Desconectar", bg=RED)

    def _toggle_rad(self):
        if self.cx_radwag.activo:
            self.cx_radwag.desconectar(); self.btn_rad.config(text="Conectar", bg=TEAL)
        else:
            ip = self.e_ip.get().strip(); port = int(self.e_port.get().strip())
            self.cx_radwag.conectar(ip, port); self.btn_rad.config(text="Desconectar", bg=RED)

    def _registrar_aba(self, datos):
        n   = len(self.ensayos) + 1
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bal = datos["balanza"]; d = 5 if "RADWAG" in bal else 2
        # Obtener RUC y razón social desde panel ABA o panel_ambiente
        ruc_val    = getattr(self, 'ruc_aba_var', None)
        razon_val  = getattr(self, 'lbl_razon_aba', None)
        ruc_txt    = ruc_val.get() if ruc_val else (
            self.panel_ambiente.ruc_var.get() if hasattr(self, 'panel_ambiente') else '—')
        razon_txt  = razon_val.cget('text') if razon_val else '—'
        if not razon_txt or razon_txt in ('', 'Sin conexión — ingresa razón social manualmente'):
            razon_txt = '—'

        ensayo = {
            "n": n, "balanza": bal, "timestamp": ts,
            "ot":        self.panel_ambiente.ot_var.get() if hasattr(self, 'panel_ambiente') else "—",
            "operador":  self.panel_ambiente.operador_var.get() if hasattr(self, 'panel_ambiente') else "—",
            "ruc":           ruc_txt,
            "razon_social":  razon_txt,
            "direccion":     getattr(self,'dir_fiscal_var',tk.StringVar()).get(),
            "id_pesa":   datos["id_pesa"],  "patron_id": datos["patron_id"],
            "nominal":   datos["nominal"],  "n_cert":    datos["n_cert"],
            "ir1":  round(datos["ir1"],  d), "it":   round(datos["it"],  d),
            "ir2":  round(datos["ir2"],  d), "ir_prom": round(datos["ir_prom"], d),
            "dct":  round(datos["dct"],  d), "dcr":  datos["dcr"],
            "decimales": d,
            "lab_patron":  datos.get("lab_patron","—"),
            "venc_patron":  datos.get("venc_patron","—"),
            "u_patron":     datos.get("u_patron", 0.060),
            "dct_mg":    round(abs(datos["dct"])*1000, 4),
            "emp_mg":    datos.get("emp_mg"),
            "conforme_emp": datos.get("conforme_emp"),
        }
        # Buscar vencimiento del patrón
        for p in self.patrones:
            if p["id"] == datos["patron_id"]:
                ensayo["venc_patron"] = p["vencimiento"]
                break
        self.ensayos.append(ensayo)
        emp_mg_val = datos.get("emp_mg") or obtener_emp_m2_directo(datos["nominal"])
        conforme_v = datos.get("conforme_emp", True)
        tag = "conforme" if conforme_v else "no_conforme"
        self.tabla.insert("","end", tags=(tag,), values=(
            n, bal, ts,
            ensayo.get("ot","—"),
            datos["id_pesa"], datos["patron_id"],
            fmt(datos["nominal"],1),
            fmt(datos["ir1"],d), fmt(datos["it"],d), fmt(datos["ir2"],d),
            fmt(datos["ir_prom"],d),
            fmt(datos["dct"],d,True),
            fdc(abs(datos["dct"])*1000, 3, True),
            fdc(emp_mg_val, 3) if emp_mg_val else "—",
            "CONFORME" if conforme_v else "NO CONFORME",
        ))
        conforme_emp = datos.get('conforme_emp', True)
        self.lbl_ult.config(
            text=f"[{bal}]  {datos['id_pesa']}  delta_mct={fmt(datos['dct'],d,True)} g  "
                 f"({'CONFORME' if conforme_emp else 'NO CONFORME'})",
            fg=GREEN if conforme_emp else RED)
        self.lbl_cont.config(text=f"Ensayos: {n}")
        registrar_log("ENSAYO_ABA", ensayo.get('operador','—'),
                      f"OT={ensayo.get('ot','—')} Pesa={datos['id_pesa']} "
                      f"dct={fmt(datos['dct'],d,True)}g EMP={'CONFORME' if conforme_emp else 'NO CONFORME'}")

        # PDF se genera manualmente desde el registro de ensayos

    def _generar_pdf_ensayo(self, ensayo):
        fecha = datetime.now().strftime('%Y%m%d_%H%M%S')
        ot = ensayo.get('ot','').replace('/','-') or 'SIN-OT'
        ruta = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF","*.pdf")],
            initialfile=f"HTA_{ot}_N{ensayo['n']}_{fecha}.pdf")
        if not ruta: return
        cond_amb = {}
        df_hobo  = None
        presion  = 1014.3
        if hasattr(self, 'panel_ambiente'):
            cond_amb = self.panel_ambiente.get_cond_amb()
            df_hobo  = self.panel_ambiente.df_hobo
            presion  = self.panel_ambiente.get_presion()
        try:
            generar_pdf_ensayo(ensayo, cond_amb, df_hobo, presion, ruta)
            messagebox.showinfo("PDF generado", f"Guardado:\n{ruta}")
            try: os.startfile(ruta)
            except: pass
        except Exception as e:
            messagebox.showerror("Error PDF", str(e))

    def _abrir_patrones(self):
        if not _verificar_password(self.root):
            return
        def cb(nuevos):
            self.patrones = nuevos
            self.panel_bio.patrones = nuevos
            self.panel_rad.patrones = nuevos
            self.panel_want.patrones = nuevos
            self.panel_bio.actualizar_patrones()
            self.panel_rad.actualizar_patrones()
            self.panel_want.actualizar_patrones()
        VentanaPatrones(self.root, self.patrones, cb)

    def _check_vigencias(self):
        alertas = []
        for p in self.patrones:
            est, _, dias = estado_vigencia(p["vencimiento"])
            if est in ("VENCIDO","POR VENCER","PROXIMO"):
                alertas.append(f"• {p['id']}: {est} ({abs(dias)}d)")
        if alertas:
            messagebox.showwarning("Alertas de Trazabilidad",
                "VIGENCIA DE PATRONES:\n\n" + "\n".join(alertas))

    def _check_alarma_mensual(self):
        """Verifica si han pasado mas de 30 dias desde la ultima descarga del HOBO."""
        cfg = cargar_config()
        ultima = cfg.get("ultima_descarga_hobo", None)
        if ultima:
            try:
                dias = (datetime.now() - datetime.strptime(ultima, "%Y-%m-%d")).days
                if dias >= 30:
                    messagebox.showwarning(
                        "Recordatorio — Descarga HOBO",
                        f"Han pasado {dias} dias desde la ultima descarga del HOBO.\n\n"
                        f"Se recomienda:\n"
                        f"• Conectar el HOBO UX100-011A\n"
                        f"• Hacer Lectura en HOBOware\n"
                        f"• Cargar CSV en la pestana Ambiente\n"
                        f"• Generar el Informe Mensual PDF\n\n"
                        f"Ultima descarga registrada: {ultima}")
            except:
                pass
        else:
            # Primera vez — no mostrar alerta pero registrar fecha
            pass

    def _exportar(self):
        if not self.ensayos:
            messagebox.showinfo("Sin datos", "No hay ensayos para exportar."); return
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV","*.csv")],
            initialfile=f"calibracion_multibalanza_{fecha}.csv")
        if not ruta: return
        with open(ruta,"w",newline="",encoding="utf-8-sig") as f:
            f.write("# METROMECANICA — Laboratorio de Calibracion\n")
            f.write("# Multi-Balanza: BIOBASE (RS-232) + RADWAG AS (WiFi)\n")
            f.write("# Procedimiento ABA | Norma ISO/IEC 17025\n")
            f.write(f"# Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Formula: delta_mct = It - (Ir1+Ir2)/2 + delta_mcr\n#\n")
            campos = ["n","balanza","timestamp","ot","operador","id_pesa",
                      "patron_id","nominal","n_cert","ir1","it","ir2","ir_prom","dct","dcr"]
            w = csv.DictWriter(f, fieldnames=campos, extrasaction='ignore')
            w.writeheader()
            for e in self.ensayos:
                row = e.copy(); d = 5 if "RADWAG" in e["balanza"] else 2
                for k in ["ir1","it","ir2","ir_prom","dct","dcr"]:
                    if isinstance(row.get(k), float):
                        row[k] = fmt(row[k], d, k in ["dct","dcr"])
                w.writerow(row)
        messagebox.showinfo("Exportado", f"CSV guardado:\n{ruta}")

    def _limpiar(self):
        if messagebox.askyesno("Limpiar", "¿Borrar todos los ensayos?"):
            self.ensayos.clear()
            for i in self.tabla.get_children(): self.tabla.delete(i)
            self.lbl_cont.config(text="Ensayos: 0"); self.lbl_ult.config(text="—")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
