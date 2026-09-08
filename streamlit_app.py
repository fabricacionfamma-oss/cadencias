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
        self.cell(0, 10, 'Reporte de Eficiencia de Produccion - FAMMA', 0, 0, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

# ==========================================
# 2. MOTOR FOTOGRÁFICO DIARIO (2 ARCHIVOS)
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

    # Identificación de columnas en Eventos
    ce_maq = encontrar_col(df_e, ['MÁQUINA', 'MAQUINA', 'CELDA'], 'EVENTOS')
    ce_fec_ini = encontrar_col(df_e, ['FECHA INICIO'], 'EVENTOS')
    ce_fec_fin = encontrar_col(df_e, ['FECHA FIN'], 'EVENTOS')
    ce_tiempo = encontrar_col(df_e, ['TIEMPO (MIN)', 'TIEMPO PRODUCTIVO', 'TIEMPO'], 'EVENTOS')
    ce_evento = encontrar_col(df_e, ['NIVEL 1', 'EVENTO', 'ESTADO'], 'EVENTOS')
    ce_buenas = encontrar_col(df_e, ['BUENAS'], 'EVENTOS')
    
    ce_nobuenas = None
    for c in df_e.columns:
        if 'NO BUENA' in c.upper() or 'MALA' in c.upper() or 'RECHAZO' in c.upper() or 'SCRAP' in c.upper():
            ce_nobuenas = c
            break

    cols_cod_e = []
    for c in df_e.columns:
        if ('CÓDIGO' in c.upper() or 'CODIGO' in c.upper()) and ('PRODUCTO' in c.upper() or 'SEMIELABORADO' in c.upper()):
            cols_cod_e.append(c)
    if not cols_cod_e:
        cols_cod_e = [c for c in df_e.columns if 'PRODUCTO/SEMIELABORADO' in c.upper() and 'DESC' not in c.upper()]
    if not cols_cod_e:
        cols_cod_e = [c for c in df_e.columns if 'PRODUCTO' in c.upper() and 'DESC' not in c.upper()]

    cols_usr = [c for c in df_e.columns if 'USUARIO' in c.upper() or 'OPERARIO' in c.upper()]

    subset_dups = [ce_maq, ce_fec_ini, ce_fec_fin, ce_tiempo, ce_buenas] + cols_cod_e
    df_e = df_e.drop_duplicates(subset=subset_dups, keep='first').copy()

    df_e['Tiempo_Min'] = pd.to_numeric(df_e[ce_tiempo].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_e['Buenas_Num'] = pd.to_numeric(df_e[ce_buenas], errors='coerce').fillna(0)
    df_e['No_Buenas_Num'] = pd.to_numeric(df_e[ce_nobuenas], errors='coerce').fillna(0) if ce_nobuenas else 0
    df_e['Total_Pzas_Fila'] = df_e['Buenas_Num'] + df_e['No_Buenas_Num']
    
    df_e = df_e[df_e[ce_evento].astype(str).str.upper().str.contains('PRODUCCI')].copy()

    df_e['Máquina_Base'] = df_e[ce_maq].astype(str).str.strip().str.upper()
    df_e['Máquina_Consol'] = df_e['Máquina_Base'].replace(r'(?i).*15.*', 'CELDA 15', regex=True)
    df_e['Fecha_Inicio_DT'] = pd.to_datetime(df_e[ce_fec_ini], errors='coerce', dayfirst=True)
    df_e['Fecha_Fin_DT'] = pd.to_datetime(df_e[ce_fec_fin], errors='coerce', dayfirst=True)
    df_e['Fecha_Str'] = df_e['Fecha_Inicio_DT'].dt.strftime('%Y-%m-%d')
    df_e['Mid_DT'] = df_e['Fecha_Inicio_DT'] + (df_e['Fecha_Fin_DT'] - df_e['Fecha_Inicio_DT']) / 2

    n_list, prods_row_list = [], []

    for idx, row in df_e.iterrows():
        mid_time = row['Mid_DT']
        maq_consol = row['Máquina_Consol']

        activos = df_e[(df_e['Máquina_Consol'] == maq_consol) &
                       (df_e['Fecha_Inicio_DT'] <= mid_time) &
                       (df_e['Fecha_Fin_DT'] >= mid_time)]

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
        pzas_asignadas = r['Total_Pzas_Fila'] / num_in_row

        for p in r['Prods_List']:
            prod_data.append({
                'Fecha_Str': r['Fecha_Str'],
                'Máquina_Consol': r['Máquina_Consol'],
                'Producto': p,
                'N': r['N'],
                'Tiempo_Min': r['Tiempo_Min'],
                'Pzas_Prod': pzas_asignadas,
                'Usuarios': [str(r.get(c, '')).strip() for c in cols_usr if pd.notna(r.get(c))]
            })

    df_prod_master = pd.DataFrame(prod_data)
    if df_prod_master.empty: raise ValueError("No se encontraron productos válidos en el archivo.")

    df_daily_prod = df_prod_master.groupby(['Fecha_Str', 'Máquina_Consol', 'Producto', 'N']).agg({
        'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
    }).reset_index()

    df_daily_prod = df_daily_prod[(df_daily_prod['Pzas_Prod'] > 0) & (df_daily_prod['Tiempo_Min'] >= 5)].copy()

    df_productos_res = df_daily_prod.groupby(['Máquina_Consol', 'Producto', 'N']).agg({
        'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
    }).reset_index()
    df_productos_res.rename(columns={'N': 'Simultaneo_Con', 'Máquina_Consol': 'Máquina'}, inplace=True)
    df_productos_res['Tiempo_Hs'] = df_productos_res['Tiempo_Min'] / 60.0

    df_e['Tiempo_Maq_Global'] = df_e['Tiempo_Min'] * (df_e['Num_Prods_Row'] / df_e['N'])
    df_e['Pzas_Maq_Global'] = df_e['Total_Pzas_Fila']

    df_daily_maq = df_e.groupby(['Fecha_Str', 'Máquina_Consol', 'N']).agg({
        'Tiempo_Maq_Global': 'sum', 'Pzas_Maq_Global': 'sum'
    }).reset_index()

    df_daily_maq = df_daily_maq[(df_daily_maq['Pzas_Maq_Global'] > 0) & (df_daily_maq['Tiempo_Maq_Global'] >= 5)].copy()

    df_global_res = df_daily_maq.groupby(['Máquina_Consol', 'N']).agg({
        'Tiempo_Maq_Global': 'sum', 'Pzas_Maq_Global': 'sum'
    }).reset_index()
    df_global_res.rename(columns={'Máquina_Consol': 'Máquina', 'Tiempo_Maq_Global': 'Tiempo_Min', 'Pzas_Maq_Global': 'Pzas_Totales'}, inplace=True)
    df_global_res['Tiempo_Hs'] = df_global_res['Tiempo_Min'] / 60.0

    valid_combos = set(zip(df_daily_prod['Fecha_Str'], df_daily_prod['Máquina_Consol'], df_daily_prod['Producto'], df_daily_prod['N']))
    usr_data = []
    for _, r in df_prod_master.iterrows():
        combo = (r['Fecha_Str'], r['Máquina_Consol'], r['Producto'], r['N'])
        if combo in valid_combos:
            usuarios = [u for u in r['Usuarios'] if u and u.upper() not in ['NAN', 'NONE', '-', '0']]
            if not usuarios: usuarios = ['Sin Operario']
            num_usr = len(usuarios)
            for u in usuarios:
                usr_data.append({
                    'Máquina': r['Máquina_Consol'], 'Producto': r['Producto'], 'Operario': u,
                    'Simultaneo_Con': r['N'], 'Tiempo_Min': r['Tiempo_Min'] / num_usr, 'Pzas_Prod': r['Pzas_Prod'] / num_usr
                })

    df_operarios_res = pd.DataFrame(usr_data)
    if not df_operarios_res.empty:
        df_operarios_res = df_operarios_res.groupby(['Máquina', 'Producto', 'Operario', 'Simultaneo_Con']).agg({
            'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
        }).reset_index()
        df_operarios_res['Tiempo_Hs'] = df_operarios_res['Tiempo_Min'] / 60.0

    col_tc = next((c for c in df_s.columns if 'TIEMPO CICLO' in c.upper() or 'CICLO' in c.upper() or 'TC' in c.upper()), df_s.columns[-1])
    col_cod = next((c for c in df_s.columns if 'CÓDIGO PRODUCTO' in c.upper() or 'CODIGO PRODUCTO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper() and 'CÓDIGO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper()), df_s.columns[4])

    df_s[col_tc] = pd.to_numeric(df_s[col_tc].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_s_min = df_s[[col_cod, col_tc]].drop_duplicates(subset=[col_cod], keep='first')
    df_s_min[col_cod] = df_s_min[col_cod].astype(str).str.strip().str.upper()

    df_productos_res = df_productos_res.merge(df_s_min, left_on='Producto', right_on=col_cod, how='left')
    df_productos_res.rename(columns={col_tc: 'TC'}, inplace=True)
    df_productos_res['TC'] = df_productos_res['TC'].fillna(0.0)

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

    return df_global_res, df_productos_res, df_operarios_res, df_daily_prod, intervalo_str

# ==========================================
# (Aquí mantienes las funciones PDF originales si quieres usarlas en la Pestaña 2)
# def generar_pdf_produccion(...)
# def generar_pagina_evolutivo(...)
# def generar_evolutivo_master(...)
# ==========================================

# ==========================================
# 5. STREAMLIT APP UI
# ==========================================
st.set_page_config(page_title="Análisis de Cadencias", layout="wide", page_icon="⚙️")

with st.sidebar:
    st.title("⚙️ Configuración")
    st.header("1. Carga de Archivos")
    uploaded_e = st.file_uploader("📂 Archivo EVENTOS", type=['csv', 'xlsx'])
    uploaded_s = st.file_uploader("📂 Archivo TIEMPOS (Ciclo)", type=['csv', 'xlsx'])

st.title("⚙️ Análisis de Cadencias y Eficiencia - FAMMA")

if not (uploaded_e and uploaded_s):
    st.info("👈 Por favor, carga los archivos de Excel/CSV en el panel lateral para visualizar las cadencias.")
else:
    try:
        with st.spinner('Procesando datos y cruzando tiempos de ciclo...'):
            df_e_raw = pd.read_csv(uploaded_e) if uploaded_e.name.endswith('.csv') else pd.read_excel(uploaded_e)
            df_s_raw = pd.read_csv(uploaded_s) if uploaded_s.name.endswith('.csv') else pd.read_excel(uploaded_s)
            
            df_global, df_productos, df_operarios, df_daily_prod, intervalo_str = procesar_datos_eventos_tc(df_e_raw, df_s_raw)

        maquinas_disp = sorted(df_daily_prod['Máquina'].unique())
        
        tab1, tab2 = st.tabs(["📊 Vista Detallada (Estilo PDF)", "📄 Exportación PDF"])

        # --- PESTAÑA 1: VISUALIZACIÓN ENFOCADA EN CADENCIA (ESTILO PDF) ---
        with tab1:
            st.markdown(f"**{intervalo_str}**")
            
            # Selector único de máquina (como ver una página del PDF)
            maq_sel = st.selectbox("📌 Seleccione la Máquina a evaluar:", maquinas_disp)
            
            st.divider()
            
            # Título de Página 
            st.markdown(f"<h2 style='text-align: center; color: #004286;'>MÁQUINA: {maq_sel}</h2>", unsafe_allow_html=True)
            
            # 1. GRAFICO DE TORTA (SIMULTANEIDAD)
            st.markdown("#### 1. Distribución de Tiempo (Hs)")
            df_maq_global = df_global[df_global['Máquina'] == maq_sel].copy()
            
            if not df_maq_global.empty:
                fig_pie, ax_pie = plt.subplots(figsize=(6, 3))
                labels = [f"Simultáneo: {int(n)}" for n in df_maq_global['N']]
                sizes = df_maq_global['Tiempo_Hs']
                colores = ['#4A90E2', '#A3D9A5', '#339933', '#A9D0F5', '#E6A8D7']
                ax_pie.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colores)
                ax_pie.axis('equal')
                st.pyplot(fig_pie)
            
            # 2. TABLA DE CADENCIAS POR PRODUCTO
            st.markdown("#### 2. Detalle de Producción y Cadencia")
            df_m_prod = df_productos[df_productos['Máquina'] == maq_sel].copy()
            
            if not df_m_prod.empty:
                # Cálculos de Cadencia
                df_m_prod['PH_Real'] = np.where(df_m_prod['Tiempo_Hs'] > 0, df_m_prod['Pzas_Prod'] / df_m_prod['Tiempo_Hs'], 0)
                df_m_prod['PH_Est'] = np.where(df_m_prod['TC'] > 0, 60 / df_m_prod['TC'], 0)
                df_m_prod['Eficiencia (%)'] = np.where(df_m_prod['PH_Est'] > 0, (df_m_prod['PH_Real'] / df_m_prod['PH_Est']) * 100, 0)
                
                # Formatear tabla para mostrar
                tabla_mostrar = df_m_prod[['Producto', 'Simultaneo_Con', 'Tiempo_Hs', 'Pzas_Prod', 'TC', 'PH_Real', 'PH_Est', 'Eficiencia (%)']].copy()
                
                st.dataframe(
                    tabla_mostrar.style.format({
                        'Tiempo_Hs': '{:.2f}',
                        'Pzas_Prod': '{:,.0f}',
                        'TC': '{:.2f}',
                        'PH_Real': '{:.1f}',
                        'PH_Est': '{:.1f}',
                        'Eficiencia (%)': '{:.1f}%'
                    }).background_gradient(subset=['Eficiencia (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )
                
            # 3. GRÁFICO EVOLUTIVO DIARIO DE CADENCIA
            st.markdown("#### 3. Evolutivo Diario de Cadencia (PH Real)")
            df_daily = df_daily_prod[df_daily_prod['Máquina'] == maq_sel].copy()
            
            if not df_daily.empty:
                df_daily = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({
                    'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
                }).reset_index()

                df_daily['Fecha_DT'] = pd.to_datetime(df_daily['Fecha_Str'])
                df_daily = df_daily.sort_values(by=['Fecha_DT', 'Producto'])

                df_daily['Tiempo_Hs'] = df_daily['Tiempo_Min'] / 60.0
                df_daily['PH_Real'] = np.where(df_daily['Tiempo_Hs'] > 0, df_daily['Pzas_Prod'] / df_daily['Tiempo_Hs'], 0)
                
                fig_line, ax_line = plt.subplots(figsize=(10, 4))
                for prod in df_daily['Producto'].unique():
                    df_p = df_daily[df_daily['Producto'] == prod]
                    ax_line.plot(df_p['Fecha_DT'], df_p['PH_Real'], marker='o', label=str(prod)[:25])

                ax_line.set_ylabel("Piezas / Hora (Real)")
                ax_line.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
                plt.xticks(rotation=45)
                ax_line.grid(True, linestyle='--', alpha=0.6)
                
                st.pyplot(fig_line)

        # --- PESTAÑA 2: EXPORTACIÓN PDF (Misma lógica que antes) ---
        with tab2:
            st.write("Aquí puedes conservar tus controles para exportar los PDFs masivos.")
            # ... (AQUÍ PEGAS LA LÓGICA DE BOTONES DEL REPORTE ANTERIOR) ...

    except Exception as e:
        st.error(f"Ocurrió un error al procesar la información: {str(e)}")
