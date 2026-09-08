import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from fpdf import FPDF
import io
import os
import tempfile

# ==========================================
# 0. FUNCIÓN DE LIMPIEZA DE TEXTO
# ==========================================
def clean_text(text):
    if pd.isna(text): return "-"
    return str(text).encode('latin-1', 'replace').decode('latin-1')

# ==========================================
# 1. CLASE PARA EL REPORTE PDF
# ==========================================
class ReportePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 66, 134)
        self.cell(0, 10, 'Reporte de Performance de Produccion', 0, 0, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

# ==========================================
# 2. MOTOR FOTOGRÁFICO DIARIO 
# ==========================================
@st.cache_data(show_spinner=False)
def procesar_datos_eventos_tc(df_e, df_s):
    df_e.columns = [str(c).strip() for c in df_e.columns]
    df_s.columns = [str(c).strip() for c in df_s.columns]

    def encontrar_col(df, busquedas, nombre_archivo):
        for b in busquedas:
            for c in df.columns:
                if b == c.upper(): return c
        for b in busquedas:
            for c in df.columns:
                if b in c.upper(): return c
        raise KeyError(f"No se encontro columna similar a {busquedas} en {nombre_archivo}")

    ce_maq = encontrar_col(df_e, ['MÁQUINA', 'MAQUINA', 'CELDA'], 'EVENTOS')
    ce_fec_ini = encontrar_col(df_e, ['FECHA INICIO'], 'EVENTOS')
    ce_fec_fin = encontrar_col(df_e, ['FECHA FIN'], 'EVENTOS')
    ce_tiempo = encontrar_col(df_e, ['TIEMPO (MIN)', 'TIEMPO PRODUCTIVO', 'TIEMPO'], 'EVENTOS')
    ce_evento = encontrar_col(df_e, ['NIVEL 1', 'EVENTO', 'ESTADO'], 'EVENTOS')
    
    ce_fab = next((c for c in df_e.columns if 'FÁBRICA' in c.upper() or 'FABRICA' in c.upper() or 'PLANTA' in c.upper()), None)
    if ce_fab:
        df_e['Fábrica'] = df_e[ce_fab].astype(str).str.strip().str.upper()
    else:
        df_e['Fábrica'] = 'GENERAL'

    df_e = df_e[df_e['Fábrica'] != 'CALIDAD'].copy()

    ce_buenas = encontrar_col(df_e, ['BUENAS'], 'EVENTOS')
    
    ce_rt = None
    for c in df_e.columns:
        if 'RETRABAJO' in c.upper() or ' RT' in c.upper() or c.upper() == 'RT':
            ce_rt = c; break
            
    ce_nobuenas = None
    for c in df_e.columns:
        if 'NO BUENA' in c.upper() or 'MALA' in c.upper() or 'RECHAZO' in c.upper() or 'SCRAP' in c.upper():
            ce_nobuenas = c; break

    cols_cod_e = []
    for c in df_e.columns:
        if ('CÓDIGO' in c.upper() or 'CODIGO' in c.upper()) and ('PRODUCTO' in c.upper() or 'SEMIELABORADO' in c.upper()):
            cols_cod_e.append(c)
    if not cols_cod_e: cols_cod_e = [c for c in df_e.columns if 'PRODUCTO/SEMIELABORADO' in c.upper() and 'DESC' not in c.upper()]
    if not cols_cod_e: cols_cod_e = [c for c in df_e.columns if 'PRODUCTO' in c.upper() and 'DESC' not in c.upper()]

    cols_usr = [c for c in df_e.columns if 'USUARIO' in c.upper() or 'OPERARIO' in c.upper()]

    subset_dups = [ce_maq, ce_fec_ini, ce_fec_fin, ce_tiempo, ce_buenas] + cols_cod_e
    df_e = df_e.drop_duplicates(subset=subset_dups, keep='first').copy()

    df_e['Tiempo_Min'] = pd.to_numeric(df_e[ce_tiempo].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_e['Es_Prod'] = df_e[ce_evento].astype(str).str.upper().str.contains('PRODUCCI')
    
    df_e['T_Prod'] = np.where(df_e['Es_Prod'], df_e['Tiempo_Min'], 0)
    df_e['T_Parada'] = np.where(~df_e['Es_Prod'], df_e['Tiempo_Min'], 0)

    df_e['Buenas_Num'] = pd.to_numeric(df_e[ce_buenas], errors='coerce').fillna(0)
    df_e['RT_Num'] = pd.to_numeric(df_e[ce_rt], errors='coerce').fillna(0) if ce_rt else 0
    df_e['Scrap_Num'] = pd.to_numeric(df_e[ce_nobuenas], errors='coerce').fillna(0) if ce_nobuenas else 0
    
    df_e['Total_Pzas_Fila'] = df_e['Buenas_Num'] + df_e['RT_Num'] + df_e['Scrap_Num']

    df_e['Máquina_Base'] = df_e[ce_maq].astype(str).str.strip().str.upper()
    df_e['Máquina_Consol'] = df_e['Máquina_Base'].replace(r'(?i).*15.*', 'CELDA 15', regex=True)

    df_e['Fecha_Inicio_DT'] = pd.to_datetime(df_e[ce_fec_ini], errors='coerce', dayfirst=True)
    df_e['Fecha_Fin_DT'] = pd.to_datetime(df_e[ce_fec_fin], errors='coerce', dayfirst=True)
    mask_ini_nat = df_e['Fecha_Inicio_DT'].isna()
    if mask_ini_nat.any(): df_e.loc[mask_ini_nat, 'Fecha_Inicio_DT'] = pd.to_datetime(df_e.loc[mask_ini_nat, ce_fec_ini], errors='coerce')
    mask_fin_nat = df_e['Fecha_Fin_DT'].isna()
    if mask_fin_nat.any(): df_e.loc[mask_fin_nat, 'Fecha_Fin_DT'] = pd.to_datetime(df_e.loc[mask_fin_nat, ce_fec_fin], errors='coerce')
    
    df_e = df_e.dropna(subset=['Fecha_Inicio_DT']).copy()
    df_e['Fecha_Str'] = df_e['Fecha_Inicio_DT'].dt.strftime('%Y-%m-%d')
    df_e['Mid_DT'] = df_e['Fecha_Inicio_DT'] + (df_e['Fecha_Fin_DT'] - df_e['Fecha_Inicio_DT']) / 2

    n_list, prods_row_list = [], []
    for idx, row in df_e.iterrows():
        mid_time = row['Mid_DT']
        maq_consol = row['Máquina_Consol']
        activos = df_e[(df_e['Máquina_Consol'] == maq_consol) & (df_e['Fecha_Inicio_DT'] <= mid_time) & (df_e['Fecha_Fin_DT'] >= mid_time)]

        prods_globales = set()
        for _, r_activa in activos.iterrows():
            for c in cols_cod_e:
                val = str(r_activa.get(c, '')).strip().upper()
                if val and val not in ['NAN', 'NONE', '-', '0']: prods_globales.add(val)

        n_calc = max(1, len(prods_globales))
        if 'LINEA 2' in maq_consol and n_calc > 2: n_calc = 2
        if 'CELDA 15' in maq_consol and n_calc > 4: n_calc = 4

        prods_propios = set()
        for c in cols_cod_e:
            val = str(row.get(c, '')).strip().upper()
            if val and val not in ['NAN', 'NONE', '-', '0']: prods_propios.add(val)

        n_list.append(n_calc)
        prods_row_list.append(list(prods_propios))

    df_e['N'] = n_list
    df_e['Prods_List'] = prods_row_list
    df_e['Num_Prods_Row'] = df_e['Prods_List'].apply(lambda x: max(1, len(x)))

    prod_data = []
    for _, r in df_e.iterrows():
        num_in_row = r['Num_Prods_Row']
        for p in r['Prods_List']:
            prod_data.append({
                'Fábrica': r['Fábrica'], 'Fecha_Str': r['Fecha_Str'], 'Máquina_Consol': r['Máquina_Consol'], 'Producto': p,
                'N': r['N'], 
                'T_Prod': r['T_Prod'], 'T_Parada': r['T_Parada'],
                'Buenas': r['Buenas_Num'] / num_in_row,
                'RT': r['RT_Num'] / num_in_row,
                'Scrap': r['Scrap_Num'] / num_in_row,
                'Usuarios': [str(r.get(c, '')).strip() for c in cols_usr if pd.notna(r.get(c))]
            })

    df_prod_master = pd.DataFrame(prod_data)
    if df_prod_master.empty: raise ValueError("No se encontraron productos válidos en el archivo.")

    df_daily_prod = df_prod_master.groupby(['Fábrica', 'Fecha_Str', 'Máquina_Consol', 'Producto', 'N']).agg({
        'T_Prod': 'sum', 'T_Parada': 'sum', 'Buenas': 'sum', 'RT': 'sum', 'Scrap': 'sum'
    }).reset_index()
    
    # ====================================================
    # FILTRO: DESCARTAR REGISTROS CON MENOS DE 1 MINUTO
    # ====================================================
    df_daily_prod = df_daily_prod[df_daily_prod['T_Prod'] >= 1.0].copy()

    df_daily_prod.rename(columns={'T_Prod': 'Tiempo_Min'}, inplace=True)
    df_daily_prod['Pzas_Prod'] = df_daily_prod['Buenas'] + df_daily_prod['RT'] + df_daily_prod['Scrap']

    col_tc = next((c for c in df_s.columns if 'TIEMPO CICLO' in c.upper() or 'CICLO' in c.upper() or 'TC' in c.upper()), df_s.columns[-1])
    col_cod = next((c for c in df_s.columns if 'CÓDIGO PRODUCTO' in c.upper() or 'CODIGO PRODUCTO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper() and 'CÓDIGO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper()), df_s.columns[4])

    df_s[col_tc] = pd.to_numeric(df_s[col_tc].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_s_min = df_s[[col_cod, col_tc]].drop_duplicates(subset=[col_cod], keep='first')
    df_s_min[col_cod] = df_s_min[col_cod].astype(str).str.strip().str.upper()

    df_daily_prod = df_daily_prod.merge(df_s_min, left_on='Producto', right_on=col_cod, how='left')
    df_daily_prod.rename(columns={col_tc: 'TC', 'Máquina_Consol': 'Máquina'}, inplace=True)
    df_daily_prod['TC'] = df_daily_prod['TC'].fillna(0.0)

    if not df_daily_prod.empty:
        fechas_ordenadas = pd.to_datetime(df_daily_prod['Fecha_Str']).sort_values()
        fecha_min = fechas_ordenadas.iloc[0].strftime('%d/%m/%Y')
        fecha_max = fechas_ordenadas.iloc[-1].strftime('%d/%m/%Y')
        intervalo_str = f"Periodo: {fecha_min} al {fecha_max}" if fecha_min != fecha_max else f"Periodo: {fecha_min}"
    else:
        intervalo_str = "Periodo: Sin datos"

    return df_prod_master, df_daily_prod, intervalo_str

# ==========================================
# 3. Y 4. REPORTES PDF 
# ==========================================
def generar_pdf_produccion(maquinas, df_productos, intervalo_str):
    pdf = ReportePDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    if df_productos.empty: return None

    for maq in maquinas:
        df_maq_prods = df_productos[df_productos['Máquina'] == maq]
        if df_maq_prods.empty: continue

        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 8, f"MÁQUINA: {maq}", ln=True)

        pdf.set_font("Arial", 'I', 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, intervalo_str, ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, "Detalle de Cadencia y Disponibilidad por Producto", ln=True)

        productos_unicos = sorted(df_maq_prods['Producto'].unique())
        for prod in productos_unicos:
            df_p_data = df_maq_prods[df_maq_prods['Producto'] == prod].sort_values('Simultaneo_Con')

            pdf.ln(3)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 7, f"CODIGO: {prod}", 0, 1, 'L', True)

            pdf.set_font("Arial", 'B', 7)
            pdf.set_fill_color(0, 66, 134); pdf.set_text_color(255, 255, 255)
            
            cols_p = [("Simult", 15), ("Hs Prd", 15), ("Hs Par", 15), ("Disp%", 14), ("B", 14), ("RT", 12), ("Scr", 12), ("PH R", 18), ("TC Ing", 18), ("PH Est", 18), ("Dif", 16), ("Perf%", 23)]
            for txt, w in cols_p: pdf.cell(w, 7, txt, 1, 0, 'C', True)
            pdf.ln()

            pdf.set_font("Arial", "", 7); pdf.set_text_color(0, 0, 0)
            for _, r in df_p_data.iterrows():
                ph_real = r['Pzas_Prod'] / r['Tiempo_Hs'] if r['Tiempo_Hs'] > 0 else 0
                ph_est = 60 / r['TC'] if r.get('TC', 0) > 0 else 0
                diff = ph_real - ph_est
                perfo = (ph_real / ph_est * 100) if ph_est > 0 else 0

                pdf.cell(15, 6, str(int(r['Simultaneo_Con'])), 1, 0, 'C')
                pdf.cell(15, 6, f"{r['Tiempo_Hs']:.2f}", 1, 0, 'C')
                pdf.cell(15, 6, f"{r.get('T_Parada_Hs', 0):.2f}", 1, 0, 'C')
                pdf.cell(14, 6, f"{r.get('Disponibilidad (%)', 0):.1f}%", 1, 0, 'C')
                pdf.cell(14, 6, str(int(r.get('Buenas_Edit', 0))), 1, 0, 'C')
                pdf.cell(12, 6, str(int(r.get('RT_Edit', 0))), 1, 0, 'C')
                pdf.cell(12, 6, str(int(r.get('Scrap_Edit', 0))), 1, 0, 'C')
                pdf.cell(18, 6, f"{ph_real:.1f}", 1, 0, 'C')
                pdf.cell(18, 6, f"{r.get('TC', 0):.4f}", 1, 0, 'C')
                pdf.cell(18, 6, f"{ph_est:.1f}", 1, 0, 'C')

                if diff < 0: pdf.set_text_color(200, 0, 0)
                else: pdf.set_text_color(0, 150, 0)
                pdf.cell(16, 6, f"{diff:.1f}", 1, 0, 'C')
                
                pdf.set_text_color(0, 0, 0)
                pdf.cell(23, 6, f"{perfo:.1f}%", 1, 1, 'C')

    nombre = "Reporte_General_Performance.pdf"
    pdf.output(nombre)
    return nombre

def generar_pagina_evolutivo(pdf, df_daily_prod, maquina_seleccionada, intervalo_str):
    df_daily = df_daily_prod[df_daily_prod['Máquina'].str.upper() == maquina_seleccionada.upper()].copy()
    if df_daily.empty: return False

    df_daily = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({'Tiempo_Min': 'sum', 'T_Parada': 'sum', 'Buenas_Edit': 'sum', 'RT_Edit': 'sum', 'Scrap_Edit': 'sum', 'Pzas_Prod': 'sum'}).reset_index()
    df_daily['Fecha_DT'] = pd.to_datetime(df_daily['Fecha_Str'])
    df_daily = df_daily.sort_values(by=['Fecha_DT', 'Producto'])

    df_daily['Tiempo_Hs'] = df_daily['Tiempo_Min'] / 60.0
    df_daily['T_Parada_Hs'] = df_daily['T_Parada'] / 60.0
    df_daily['Disp'] = np.where((df_daily['Tiempo_Hs'] + df_daily['T_Parada_Hs']) > 0, (df_daily['Tiempo_Hs'] / (df_daily['Tiempo_Hs'] + df_daily['T_Parada_Hs'])) * 100, 0)
    
    df_daily['PH_Real'] = np.where(df_daily['Tiempo_Hs'] > 0, df_daily['Pzas_Prod'] / df_daily['Tiempo_Hs'], 0)
    df_daily['PH_Est'] = np.where(df_daily['TC'] > 0, 60 / df_daily['TC'], 0)
    df_daily['Perfo'] = np.where(df_daily['PH_Est'] > 0, (df_daily['PH_Real'] / df_daily['PH_Est']) * 100, 0)

    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"HISTORICO DE PRODUCCION DIARIO: {maquina_seleccionada}", ln=True, align='C')

    pdf.set_font("Arial", 'I', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, intervalo_str, ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    fig, ax = plt.subplots(figsize=(10, 4))
    for prod in df_daily['Producto'].unique():
        df_prod = df_daily[df_daily['Producto'] == prod]
        ax.plot(df_prod['Fecha_DT'], df_prod['PH_Real'], marker='o', label=str(prod)[:20])

    ax.set_title("Evolucion de Cadencia por Codigo de Producto", fontweight='bold', fontsize=10)
    ax.set_xlabel("Fechas de Produccion")
    ax.set_ylabel("Piezas / Hora (Real)")

    fechas_unicas = sorted(df_daily['Fecha_DT'].unique())
    ax.set_xticks(fechas_unicas)
    ax.set_xticklabels([pd.to_datetime(x).strftime('%d/%m/%Y') for x in fechas_unicas], rotation=45, ha='right', fontsize=7)
    
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=7, title="Codigos")
    ax.grid(True, linestyle=':', alpha=0.6)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        fig.savefig(tmp.name, bbox_inches='tight')
        chart = tmp.name
    plt.close(fig)

    pdf.image(chart, x=10, w=190)
    os.remove(chart)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 7)
    pdf.set_fill_color(0, 66, 134); pdf.set_text_color(255, 255, 255)

    cols = [("Fecha", 18), ("Codigo", 45), ("Hs Prd", 12), ("Hs Par", 12), ("Disp%", 13), ("B", 12), ("RT", 10), ("Scr", 10), ("PH R", 14), ("PH Est", 14), ("Dif", 15), ("Perf%", 15)]
    for txt, w in cols: pdf.cell(w, 8, txt, 1, 0, 'C', True)
    pdf.ln()

    pdf.set_font("Arial", "", 7); pdf.set_text_color(0, 0, 0)

    for _, r in df_daily.iterrows():
        pdf.cell(18, 6, pd.to_datetime(r['Fecha_Str']).strftime('%d/%m/%Y'), 1, 0, 'C')
        pdf.cell(45, 6, clean_text(r['Producto'])[:32], 1, 0, 'L')
        pdf.cell(12, 6, f"{r['Tiempo_Hs']:.1f}", 1, 0, 'C')
        pdf.cell(12, 6, f"{r['T_Parada_Hs']:.1f}", 1, 0, 'C')
        pdf.cell(13, 6, f"{r['Disp']:.0f}%", 1, 0, 'C')
        pdf.cell(12, 6, str(int(r['Buenas_Edit'])), 1, 0, 'C')
        pdf.cell(10, 6, str(int(r['RT_Edit'])), 1, 0, 'C')
        pdf.cell(10, 6, str(int(r['Scrap_Edit'])), 1, 0, 'C')
        pdf.cell(14, 6, f"{r['PH_Real']:.1f}", 1, 0, 'C')
        pdf.cell(14, 6, f"{r['PH_Est']:.1f}", 1, 0, 'C')

        diff = r['PH_Real'] - r['PH_Est']
        if diff < 0: pdf.set_text_color(200, 0, 0)
        else: pdf.set_text_color(0, 150, 0)
        pdf.cell(15, 6, f"{diff:.1f}", 1, 0, 'C')

        pdf.set_text_color(0, 0, 0)
        pdf.cell(15, 6, f"{r['Perfo']:.1f}%", 1, 1, 'C')

    return True

def generar_evolutivo_master(df_daily_prod, maquinas, modo, intervalo_str):
    archivos_generados = []
    if modo == '1':
        for maq in maquinas:
            pdf = ReportePDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            if generar_pagina_evolutivo(pdf, df_daily_prod, maq, intervalo_str):
                nombre = f"Reporte_Evolutivo_{maq.replace(' ','_')}.pdf"
                pdf.output(nombre)
                archivos_generados.append(nombre)
    elif modo == '2':
        pdf = ReportePDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        paginas_agregadas = False
        for maq in maquinas:
            if generar_pagina_evolutivo(pdf, df_daily_prod, maq, intervalo_str):
                paginas_agregadas = True
        if paginas_agregadas:
            nombre = "Reporte_Evolutivo_Consolidado.pdf"
            pdf.output(nombre)
            archivos_generados.append(nombre)

    return archivos_generados

# ==========================================
# 5. STREAMLIT APP UI
# ==========================================
st.set_page_config(page_title="Análisis de Cadencias", layout="wide", page_icon="⚙️")

with st.sidebar:
    st.title("⚙️ Configuración")
    st.header("1. Carga de Archivos")
    uploaded_e = st.file_uploader("📂 Archivo EVENTOS", type=['csv', 'xlsx'])
    uploaded_s = st.file_uploader("📂 Archivo TIEMPOS (Ciclo)", type=['csv', 'xlsx'])

st.title("⚙️ Análisis de Cadencias y Performance")

if not (uploaded_e and uploaded_s):
    st.info("👈 Por favor, carga los archivos de Excel/CSV en el panel lateral para visualizar las cadencias.")
else:
    try:
        with st.spinner('Procesando datos, desglosando piezas y cruzando tiempos de ciclo...'):
            df_e_raw = pd.read_csv(uploaded_e) if uploaded_e.name.endswith('.csv') else pd.read_excel(uploaded_e)
            df_s_raw = pd.read_csv(uploaded_s) if uploaded_s.name.endswith('.csv') else pd.read_excel(uploaded_s)
            
            df_prod_master, df_daily_prod, intervalo_str = procesar_datos_eventos_tc(df_e_raw, df_s_raw)

        # --- SISTEMA DE MEMORIA GLOBAL (A prueba de formatos viejos) ---
        if "correcciones_cadencia" not in st.session_state:
            st.session_state["correcciones_cadencia"] = {}

        df_daily_prod['Clave_Unica'] = df_daily_prod['Fecha_Str'] + "_" + df_daily_prod['Máquina'] + "_" + df_daily_prod['Producto']
        
        # INYECTAR LAS CORRECCIONES EN LA BASE DE DATOS TEMPORAL
        df_daily_prod['Buenas_Edit'] = df_daily_prod['Buenas']
        df_daily_prod['RT_Edit'] = df_daily_prod['RT']
        df_daily_prod['Scrap_Edit'] = df_daily_prod['Scrap']

        for clave, edits in st.session_state["correcciones_cadencia"].items():
            if isinstance(edits, dict):
                mask = df_daily_prod['Clave_Unica'] == clave
                df_daily_prod.loc[mask, 'Buenas_Edit'] = edits.get('Buenas', 0)
                df_daily_prod.loc[mask, 'RT_Edit'] = edits.get('RT', 0)
                df_daily_prod.loc[mask, 'Scrap_Edit'] = edits.get('Scrap', 0)

        # El Pzas_Prod oficial ahora es la suma de los campos editados
        df_daily_prod['Pzas_Prod'] = df_daily_prod['Buenas_Edit'] + df_daily_prod['RT_Edit'] + df_daily_prod['Scrap_Edit']

        # ====================================================================================
        # RECALCULAR DF_PRODUCTOS (RESUMEN GENERAL) BASADO EN LAS CORRECCIONES
        # ====================================================================================
        df_daily_prod['Pzas_Est_Dia'] = np.where(df_daily_prod['TC'] > 0, (df_daily_prod['Tiempo_Min'] / df_daily_prod['TC']), 0)
        df_productos = df_daily_prod.groupby(['Máquina', 'Producto', 'N']).agg({
            'Tiempo_Min': 'sum',
            'T_Parada': 'sum',
            'Buenas': 'sum', 'RT': 'sum', 'Scrap': 'sum',
            'Buenas_Edit': 'sum', 'RT_Edit': 'sum', 'Scrap_Edit': 'sum',
            'Pzas_Prod': 'sum',
            'Pzas_Est_Dia': 'sum'
        }).reset_index()
        
        df_productos.rename(columns={'N': 'Simultaneo_Con'}, inplace=True)
        df_productos['Tiempo_Hs'] = df_productos['Tiempo_Min'] / 60.0
        df_productos['T_Parada_Hs'] = df_productos['T_Parada'] / 60.0
        
        # Disponibilidad = T_Prod / (T_Prod + T_Parada)
        df_productos['Disponibilidad (%)'] = np.where((df_productos['Tiempo_Min'] + df_productos['T_Parada']) > 0, 
                                                      (df_productos['Tiempo_Min'] / (df_productos['Tiempo_Min'] + df_productos['T_Parada'])) * 100, 0)

        df_productos['TC'] = np.where(df_productos['Pzas_Est_Dia'] > 0, df_productos['Tiempo_Min'] / df_productos['Pzas_Est_Dia'], 0)
        
        maquinas_disp = sorted(df_daily_prod['Máquina'].unique())
        
        # --- CREACIÓN DE LAS 3 PESTAÑAS ---
        tab1, tab2, tab3 = st.tabs(["📊 Dashboard de Máquina", "🛠️ Editor Masivo por Planta", "📄 Exportación PDF"])

        # =====================================================================
        # PESTAÑA 1: VISUALIZACIÓN WEB DE SÓLO LECTURA
        # =====================================================================
        with tab1:
            st.markdown(f"**{intervalo_str}**")
            maq_sel = st.selectbox("📌 Seleccione la Máquina a evaluar:", maquinas_disp)
            st.divider()
            
            st.markdown(f"<h2 style='text-align: center; color: #004286;'>MÁQUINA: {maq_sel}</h2>", unsafe_allow_html=True)
            
            st.markdown("#### 1. Resumen General por Producto")
            df_m_prod = df_productos[df_productos['Máquina'] == maq_sel].copy()
            if not df_m_prod.empty:
                df_m_prod['PH Real'] = np.where(df_m_prod['Tiempo_Hs'] > 0, df_m_prod['Pzas_Prod'] / df_m_prod['Tiempo_Hs'], 0)
                df_m_prod['PH_Est'] = np.where(df_m_prod['TC'] > 0, 60 / df_m_prod['TC'], 0)
                df_m_prod['Performance (%)'] = np.where(df_m_prod['PH_Est'] > 0, (df_m_prod['PH Real'] / df_m_prod['PH_Est']) * 100, 0)
                
                df_m_prod.rename(columns={'TC': 'TC Ingenieria'}, inplace=True)
                
                tabla_mostrar = df_m_prod[['Producto', 'Simultaneo_Con', 'Tiempo_Hs', 'T_Parada_Hs', 'Disponibilidad (%)', 'Buenas_Edit', 'RT_Edit', 'Scrap_Edit', 'TC Ingenieria', 'PH Real', 'PH_Est', 'Performance (%)']].copy()
                st.dataframe(
                    tabla_mostrar.style.format({
                        'Tiempo_Hs': '{:.2f}', 'T_Parada_Hs': '{:.2f}', 'Disponibilidad (%)': '{:.1f}%',
                        'Buenas_Edit': '{:,.0f}', 'RT_Edit': '{:,.0f}', 'Scrap_Edit': '{:,.0f}', 'TC Ingenieria': '{:.4f}',
                        'PH Real': '{:.1f}', 'PH_Est': '{:.1f}', 'Performance (%)': '{:.1f}%'
                    }).background_gradient(subset=['Performance (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )
                
            st.markdown("#### 2. Evolutivo Diario de Cadencia (PH Real)")
            df_daily = df_daily_prod[df_daily_prod['Máquina'] == maq_sel].copy()
            if not df_daily.empty:
                df_daily_grp = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'}).reset_index()
                df_daily_grp['Fecha_DT'] = pd.to_datetime(df_daily_grp['Fecha_Str'])
                df_daily_grp = df_daily_grp.sort_values(by=['Fecha_DT', 'Producto'])

                df_daily_grp['Tiempo_Hs'] = df_daily_grp['Tiempo_Min'] / 60.0
                df_daily_grp['PH_Real'] = np.where(df_daily_grp['Tiempo_Hs'] > 0, df_daily_grp['Pzas_Prod'] / df_daily_grp['Tiempo_Hs'], 0)
                df_daily_grp['PH_Est'] = np.where(df_daily_grp['TC'] > 0, 60 / df_daily_grp['TC'], 0)
                
                fig_line, ax_line = plt.subplots(figsize=(10, 4))
                for prod in df_daily_grp['Producto'].unique():
                    df_p = df_daily_grp[df_daily_grp['Producto'] == prod]
                    ax_line.plot(df_p['Fecha_DT'], df_p['PH_Real'], marker='o', label=str(prod)[:25])

                ax_line.set_ylabel("Piezas / Hora (PH Real)")
                fechas_unicas_web = sorted(df_daily_grp['Fecha_DT'].unique())
                ax_line.set_xticks(fechas_unicas_web)
                ax_line.set_xticklabels([pd.to_datetime(x).strftime('%d/%m/%Y') for x in fechas_unicas_web], rotation=45, ha='right')
                ax_line.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
                ax_line.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig_line)
                
                st.markdown("#### 3. Detalle Diario (Día a Día)")
                df_diario_ui = df_daily_prod[df_daily_prod['Máquina'] == maq_sel].copy()
                
                df_diario_ui['Tiempo_Hs'] = df_diario_ui['Tiempo_Min'] / 60.0
                df_diario_ui['T_Parada_Hs'] = df_diario_ui['T_Parada'] / 60.0
                df_diario_ui['Disponibilidad (%)'] = np.where((df_diario_ui['Tiempo_Min'] + df_diario_ui['T_Parada']) > 0, 
                                                              (df_diario_ui['Tiempo_Min'] / (df_diario_ui['Tiempo_Min'] + df_diario_ui['T_Parada'])) * 100, 0)
                
                df_diario_ui['PH Real'] = np.where(df_diario_ui['Tiempo_Hs'] > 0, df_diario_ui['Pzas_Prod'] / df_diario_ui['Tiempo_Hs'], 0)
                df_diario_ui['PH_Est'] = np.where(df_diario_ui['TC'] > 0, 60 / df_diario_ui['TC'], 0)
                df_diario_ui['Performance (%)'] = np.where(df_diario_ui['PH_Est'] > 0, (df_diario_ui['PH Real'] / df_diario_ui['PH_Est']) * 100, 0)
                df_diario_ui['Fecha'] = pd.to_datetime(df_diario_ui['Fecha_Str']).dt.strftime('%d/%m/%Y')
                
                df_diario_ui.rename(columns={'TC': 'TC Ingenieria'}, inplace=True)

                tabla_diaria = df_diario_ui[['Fecha', 'Producto', 'Tiempo_Hs', 'T_Parada_Hs', 'Disponibilidad (%)', 'Buenas_Edit', 'RT_Edit', 'Scrap_Edit', 'TC Ingenieria', 'PH Real', 'PH_Est', 'Performance (%)']].iloc[::-1].reset_index(drop=True)
                
                st.info("💡 Si deseas editar la producción y que los cálculos se actualicen, ve a la pestaña **'🛠️ Editor Masivo por Planta'**.")
                st.dataframe(
                    tabla_diaria.style.format({
                        'Tiempo_Hs': '{:.2f}', 'T_Parada_Hs': '{:.2f}', 'Disponibilidad (%)': '{:.1f}%',
                        'Buenas_Edit': '{:,.0f}', 'RT_Edit': '{:,.0f}', 'Scrap_Edit': '{:,.0f}', 'TC Ingenieria': '{:.4f}',
                        'PH Real': '{:.1f}', 'PH_Est': '{:.1f}', 'Performance (%)': '{:.1f}%'
                    }).background_gradient(subset=['Performance (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )

        # =====================================================================
        # PESTAÑA 2: EDITOR MASIVO SEPARADO POR PLANTA
        # =====================================================================
        with tab2:
            st.markdown("### 🛠️ Corrección de Producción (Por Planta)")
            st.write("Edita las **Piezas Buenas, RT o Scrap** de cada día. El sistema recalculará automáticamente la Pieza/Hora Real, el TC Real y la Performance.")
            
            df_edit_global = df_daily_prod.copy()
            df_edit_global['Fecha'] = pd.to_datetime(df_edit_global['Fecha_Str']).dt.strftime('%d/%m/%Y')
            df_edit_global['Tiempo_Hs'] = df_edit_global['Tiempo_Min'] / 60.0
            df_edit_global['T_Parada_Hs'] = df_edit_global['T_Parada'] / 60.0
            df_edit_global['Disponibilidad (%)'] = np.where((df_edit_global['Tiempo_Min'] + df_edit_global['T_Parada']) > 0, 
                                                            (df_edit_global['Tiempo_Min'] / (df_edit_global['Tiempo_Min'] + df_edit_global['T_Parada'])) * 100, 0)
            
            df_edit_global['PH_Est'] = np.where(df_edit_global['TC'] > 0, 60 / df_edit_global['TC'], 0)
            df_edit_global.rename(columns={'TC': 'TC Ingenieria'}, inplace=True)
            
            plantas_disp = sorted(df_edit_global['Fábrica'].unique())
            
            if plantas_disp:
                tabs_plantas = st.tabs([f"🏭 Planta: {p}" for p in plantas_disp])
                
                for idx, planta in enumerate(plantas_disp):
                    with tabs_plantas[idx]:
                        df_planta = df_edit_global[df_edit_global['Fábrica'] == planta].copy()
                        
                        # Definir la estructura visual
                        tabla_masiva = df_planta[['Clave_Unica', 'Fecha', 'Máquina', 'Producto', 'Tiempo_Hs', 'T_Parada_Hs', 'Disponibilidad (%)', 'Buenas', 'RT', 'Scrap', 'TC Ingenieria', 'PH_Est']].copy()
                        
                        # Inyectar las columnas Editables
                        tabla_masiva['Buenas (✏️)'] = df_planta['Buenas_Edit']
                        tabla_masiva['RT (✏️)'] = df_planta['RT_Edit']
                        tabla_masiva['Scrap (✏️)'] = df_planta['Scrap_Edit']
                        
                        # Realizar los cálculos sobre esas columnas editables
                        tabla_masiva['Total Editado'] = tabla_masiva['Buenas (✏️)'] + tabla_masiva['RT (✏️)'] + tabla_masiva['Scrap (✏️)']
                        tabla_masiva['PH Real'] = np.where(tabla_masiva['Tiempo_Hs'] > 0, tabla_masiva['Total Editado'] / tabla_masiva['Tiempo_Hs'], 0)
                        tabla_masiva['TC Real'] = np.where(tabla_masiva['PH Real'] > 0, 60 / tabla_masiva['PH Real'], 0)
                        tabla_masiva['Performance Real (%)'] = np.where(tabla_masiva['PH_Est'] > 0, (tabla_masiva['PH Real'] / tabla_masiva['PH_Est']) * 100, 0)
                        
                        # Reordenar las columnas
                        tabla_masiva = tabla_masiva[['Clave_Unica', 'Fecha', 'Máquina', 'Producto', 'Tiempo_Hs', 'T_Parada_Hs', 'Disponibilidad (%)', 'Buenas', 'RT', 'Scrap', 'Buenas (✏️)', 'RT (✏️)', 'Scrap (✏️)', 'Total Editado', 'TC Ingenieria', 'PH_Est', 'PH Real', 'TC Real', 'Performance Real (%)']]

                        st.info(f"Mostrando datos de: **{planta}**. Al modificar las casillas con ✏️, presiona Enter para ver el impacto.")
                        
                        edited_df = st.data_editor(
                            tabla_masiva.style.format({
                                'Tiempo_Hs': '{:.2f}', 'T_Parada_Hs': '{:.2f}', 'Disponibilidad (%)': '{:.1f}%',
                                'Buenas': '{:,.0f}', 'RT': '{:,.0f}', 'Scrap': '{:,.0f}', 
                                'Buenas (✏️)': '{:.0f}', 'RT (✏️)': '{:.0f}', 'Scrap (✏️)': '{:.0f}', 'Total Editado': '{:.0f}',
                                'TC Ingenieria': '{:.4f}', 'PH_Est': '{:.1f}', 'PH Real': '{:.1f}', 'TC Real': '{:.4f}', 'Performance Real (%)': '{:.1f}%'
                            }).background_gradient(subset=['Performance Real (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                            column_config={
                                "Clave_Unica": None,
                                "Fecha": st.column_config.Column(disabled=True),
                                "Máquina": st.column_config.Column(disabled=True),
                                "Producto": st.column_config.Column(disabled=True),
                                "Tiempo_Hs": st.column_config.NumberColumn("Hs Prod", disabled=True),
                                "T_Parada_Hs": st.column_config.NumberColumn("Hs Parada", disabled=True),
                                "Disponibilidad (%)": st.column_config.NumberColumn("Disp(%)", disabled=True),
                                "Buenas": st.column_config.NumberColumn("B (Wiidem)", disabled=True),
                                "RT": st.column_config.NumberColumn("RT (Wiidem)", disabled=True),
                                "Scrap": st.column_config.NumberColumn("Scrap (Wiidem)", disabled=True),
                                "Total Editado": st.column_config.NumberColumn("Total", disabled=True),
                                "TC Ingenieria": st.column_config.NumberColumn(disabled=True),
                                "PH_Est": st.column_config.NumberColumn("PH Estimada", disabled=True),
                                "PH Real": st.column_config.NumberColumn(disabled=True),
                                "TC Real": st.column_config.NumberColumn(disabled=True),
                                "Performance Real (%)": st.column_config.NumberColumn(disabled=True),
                                "Buenas (✏️)": st.column_config.NumberColumn("Buenas (✏️)", min_value=0, step=1),
                                "RT (✏️)": st.column_config.NumberColumn("RT (✏️)", min_value=0, step=1),
                                "Scrap (✏️)": st.column_config.NumberColumn("Scrap (✏️)", min_value=0, step=1)
                            },
                            use_container_width=True, 
                            hide_index=True,
                            key=f"editor_{planta}"
                        )
                        
                        # Detectar y guardar cambios
                        hubo_cambio = False
                        for index, row in edited_df.iterrows():
                            b_act = row['Buenas (✏️)']
                            rt_act = row['RT (✏️)']
                            s_act = row['Scrap (✏️)']
                            clave = row['Clave_Unica']
                            
                            b_orig = row['Buenas']
                            rt_orig = row['RT']
                            s_orig = row['Scrap']
                            
                            mem = st.session_state["correcciones_cadencia"].get(clave, {})
                            
                            if (b_act != b_orig or rt_act != rt_orig or s_act != s_orig) or (clave in st.session_state["correcciones_cadencia"]):
                                if mem.get('Buenas') != b_act or mem.get('RT') != rt_act or mem.get('Scrap') != s_act:
                                    st.session_state["correcciones_cadencia"][clave] = {'Buenas': b_act, 'RT': rt_act, 'Scrap': s_act}
                                    hubo_cambio = True

                        # Sistema de Descarga Excel Exclusivo por Planta
                        st.markdown("---")
                        col_dl1, col_dl2 = st.columns([1, 4])
                        with col_dl1:
                            if not edited_df.empty:
                                df_xlsx = edited_df.drop(columns=['Clave_Unica']).copy()
                                output = io.BytesIO()
                                
                                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                                    sheet_name = f'Cadencias_{planta}'[:31] 
                                    df_xlsx.to_excel(writer, index=False, sheet_name=sheet_name, startrow=2)
                                    
                                    workbook = writer.book
                                    worksheet = writer.sheets[sheet_name]
                                    
                                    title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#004286', 'font_color': 'white'})
                                    header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
                                    fmt_0 = workbook.add_format({'num_format': '#,##0', 'align': 'center'})
                                    fmt_1 = workbook.add_format({'num_format': '#,##0.0', 'align': 'center'})
                                    fmt_2 = workbook.add_format({'num_format': '#,##0.00', 'align': 'center'})
                                    fmt_4 = workbook.add_format({'num_format': '0.0000', 'align': 'center'})
                                    fmt_pct = workbook.add_format({'num_format': '0.0"%"', 'align': 'center'})
                                    fmt_txt = workbook.add_format({'align': 'center'})
                                    fmt_left = workbook.add_format({'align': 'left'})
                                    
                                    num_cols = len(df_xlsx.columns)
                                    worksheet.merge_range(0, 0, 0, num_cols - 1, f"REPORTE DE PRODUCCIÓN Y CADENCIAS - PLANTA: {planta.upper()}", title_format)
                                    
                                    for col_num, col_name in enumerate(df_xlsx.columns):
                                        worksheet.write(1, col_num, col_name, header_format)
                                        
                                    worksheet.set_column('A:A', 12, fmt_txt)    
                                    worksheet.set_column('B:B', 20, fmt_left)   
                                    worksheet.set_column('C:C', 30, fmt_left)   
                                    worksheet.set_column('D:E', 12, fmt_2)      
                                    worksheet.set_column('F:F', 12, fmt_pct)    
                                    worksheet.set_column('G:I', 10, fmt_0)      
                                    worksheet.set_column('J:L', 12, fmt_0)      
                                    worksheet.set_column('M:M', 12, fmt_0)      
                                    worksheet.set_column('N:N', 12, fmt_4)      
                                    worksheet.set_column('O:O', 12, fmt_1)      
                                    worksheet.set_column('P:P', 12, fmt_1)      
                                    worksheet.set_column('Q:Q', 12, fmt_4)      
                                    worksheet.set_column('R:R', 15, fmt_pct)    
                                    
                                    worksheet.set_row(0, 30)
                                
                                st.download_button(
                                    label=f"📥 Descargar Excel Formateado - {planta}",
                                    data=output.getvalue(),
                                    file_name=f"Correciones_Cadencia_{planta}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"dl_excel_{planta}"
                                )

                        if hubo_cambio:
                            st.success("✅ Recalculando... Aplicando cambios a la producción.")
                            st.rerun()

        # =====================================================================
        # PESTAÑA 3: MENÚ DE EXPORTACIÓN A PDF
        # =====================================================================
        with tab3:
            st.markdown("### 📄 Configuración de Reportes PDF")
            st.info("💡 **Nota:** Los reportes PDF se generarán aplicando todas las correcciones que hayas realizado en la pestaña del **Editor Masivo**.")
            
            opcion_reporte = st.radio(
                "Selecciona qué reporte deseas generar:", 
                ["1. Reporte General (Torta, Producto y Operario)", 
                 "2. Reporte Evolutivo Diario (Gráfico de Líneas)", 
                 "3. Generar AMBOS"]
            )

            maquinas_a_procesar = []
            modo_descarga = '1'

            if "2" in opcion_reporte or "3" in opcion_reporte:
                st.markdown("#### ⚙️ Selección de Máquinas para Evolutivo")
                todas_maquinas = st.checkbox("Procesar TODAS las máquinas disponibles", value=True)
                
                if todas_maquinas:
                    maquinas_a_procesar = maquinas_disp
                else:
                    maquinas_a_procesar = st.multiselect("Elige las máquinas a exportar:", maquinas_disp, default=maquinas_disp[:1])

                if len(maquinas_a_procesar) > 1:
                    modo_radio = st.radio("Formato de Exportación Evolutivo:", ["1. PDFs Individuales por Máquina", "2. Un solo PDF Consolidado"])
                    modo_descarga = '1' if "1." in modo_radio else '2'

            st.divider()
            
            if st.button("🚀 Procesar Documentos PDF", type="primary"):
                with st.spinner("Construyendo archivos PDF..."):
                    
                    if ("1" in opcion_reporte or "3" in opcion_reporte):
                        maqs_general = sorted(df_productos['Máquina'].unique())
                        res_gen = generar_pdf_produccion(maqs_general, df_productos, intervalo_str)
                        
                        if res_gen:
                            st.success(f"✅ Reporte General Generado.")
                            st.download_button(
                                label="📥 Descargar Reporte General (.pdf)", 
                                data=res_gen, 
                                file_name="Reporte_General_Performance.pdf", 
                                mime="application/pdf"
                            )
                    
                    if ("2" in opcion_reporte or "3" in opcion_reporte) and maquinas_a_procesar:
                        archivos_evo = generar_evolutivo_master(df_daily_prod, maquinas_a_procesar, modo_descarga, intervalo_str)
                        
                        for arch in archivos_evo:
                            if os.path.exists(arch):
                                st.success(f"✅ {arch} Generado.")
                                with open(arch, "rb") as f:
                                    st.download_button(
                                        label=f"📥 Descargar {arch}", 
                                        data=f, 
                                        file_name=arch, 
                                        mime="application/pdf", 
                                        key=arch
                                    )

    except Exception as e:
        import traceback
        st.error(f"Ocurrió un error al procesar la información: {str(e)}")
        st.code(traceback.format_exc())
