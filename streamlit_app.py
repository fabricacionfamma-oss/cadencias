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
        with st.spinner('Procesando datos, unificando fechas y cruzando tiempos de ciclo...'):
            df_e_raw = pd.read_csv(uploaded_e) if uploaded_e.name.endswith('.csv') else pd.read_excel(uploaded_e)
            df_s_raw = pd.read_csv(uploaded_s) if uploaded_s.name.endswith('.csv') else pd.read_excel(uploaded_s)
            
            df_global, df_productos, df_operarios, df_daily_prod, intervalo_str = procesar_datos_eventos_tc(df_e_raw, df_s_raw)

        # --- SISTEMA DE MEMORIA GLOBAL PARA EDICIONES MASIVAS ---
        # Diccionario para guardar las correcciones con llave: "Fecha_Maquina_Producto"
        if "correcciones_cadencia" not in st.session_state:
            st.session_state["correcciones_cadencia"] = {}

        # Aplicar las correcciones guardadas al DataFrame PRINCIPAL antes de hacer cualquier cálculo
        df_daily_prod['Clave_Unica'] = df_daily_prod['Fecha_Str'] + "_" + df_daily_prod['Máquina'] + "_" + df_daily_prod['Producto']
        
        for clave, nuevo_ph in st.session_state["correcciones_cadencia"].items():
            if nuevo_ph > 0:
                # Si el usuario modificó el PH, recalculamos y forzamos el nuevo TC en la base de datos temporal
                nuevo_tc = 60 / nuevo_ph
                df_daily_prod.loc[df_daily_prod['Clave_Unica'] == clave, 'TC'] = nuevo_tc

        maquinas_disp = sorted(df_daily_prod['Máquina'].unique())
        
        # --- CREACIÓN DE LAS 3 PESTAÑAS ---
        tab1, tab3, tab2 = st.tabs(["📊 Vista Detallada de Máquina", "🛠️ Editor Masivo de Cadencias", "📄 Exportación PDF"])

        # =====================================================================
        # PESTAÑA 1: VISUALIZACIÓN WEB (MÁQUINA INDIVIDUAL)
        # =====================================================================
        with tab1:
            st.markdown(f"**{intervalo_str}**")
            maq_sel = st.selectbox("📌 Seleccione la Máquina a evaluar:", maquinas_disp)
            st.divider()
            
            st.markdown(f"<h2 style='text-align: center; color: #004286;'>MÁQUINA: {maq_sel}</h2>", unsafe_allow_html=True)
            
            st.markdown("#### 1. Distribución de Tiempo Total (Hs)")
            df_maq_global = df_global[df_global['Máquina'] == maq_sel].copy()
            if not df_maq_global.empty:
                col_pie1, col_pie2, col_pie3 = st.columns([1, 2, 1])
                with col_pie2:
                    fig_pie, ax_pie = plt.subplots(figsize=(4, 2.5))
                    labels = [f"Simultáneo: {int(n)}" for n in df_maq_global['N']]
                    sizes = df_maq_global['Tiempo_Hs']
                    colores = ['#4A90E2', '#A3D9A5', '#339933', '#A9D0F5', '#E6A8D7']
                    ax_pie.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colores)
                    ax_pie.axis('equal')
                    st.pyplot(fig_pie)
            
            st.markdown("#### 2. Resumen General por Producto")
            df_m_prod = df_productos[df_productos['Máquina'] == maq_sel].copy()
            if not df_m_prod.empty:
                df_m_prod['PH Wiidem'] = np.where(df_m_prod['Tiempo_Hs'] > 0, df_m_prod['Pzas_Prod'] / df_m_prod['Tiempo_Hs'], 0)
                df_m_prod['PH_Est'] = np.where(df_m_prod['TC'] > 0, 60 / df_m_prod['TC'], 0)
                df_m_prod['Performance Wiidem (%)'] = np.where(df_m_prod['PH_Est'] > 0, (df_m_prod['PH Wiidem'] / df_m_prod['PH_Est']) * 100, 0)
                
                df_m_prod.rename(columns={'Pzas_Prod': 'Piezas Wiidem', 'TC': 'TC Ingenieria'}, inplace=True)
                
                tabla_mostrar = df_m_prod[['Producto', 'Simultaneo_Con', 'Tiempo_Hs', 'Piezas Wiidem', 'TC Ingenieria', 'PH Wiidem', 'PH_Est', 'Performance Wiidem (%)']].copy()
                st.dataframe(
                    tabla_mostrar.style.format({
                        'Tiempo_Hs': '{:.2f}', 'Piezas Wiidem': '{:,.0f}', 'TC Ingenieria': '{:.4f}',
                        'PH Wiidem': '{:.1f}', 'PH_Est': '{:.1f}', 'Performance Wiidem (%)': '{:.1f}%'
                    }).background_gradient(subset=['Performance Wiidem (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )
                
            st.markdown("#### 3. Evolutivo Diario de Cadencia (PH Wiidem)")
            df_daily = df_daily_prod[df_daily_prod['Máquina'] == maq_sel].copy()
            if not df_daily.empty:
                df_daily_grp = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'}).reset_index()
                df_daily_grp['Fecha_DT'] = pd.to_datetime(df_daily_grp['Fecha_Str'])
                df_daily_grp = df_daily_grp.sort_values(by=['Fecha_DT', 'Producto'])

                df_daily_grp['Tiempo_Hs'] = df_daily_grp['Tiempo_Min'] / 60.0
                df_daily_grp['PH_Wiidem'] = np.where(df_daily_grp['Tiempo_Hs'] > 0, df_daily_grp['Pzas_Prod'] / df_daily_grp['Tiempo_Hs'], 0)
                df_daily_grp['PH_Est'] = np.where(df_daily_grp['TC'] > 0, 60 / df_daily_grp['TC'], 0)
                
                fig_line, ax_line = plt.subplots(figsize=(10, 4))
                for prod in df_daily_grp['Producto'].unique():
                    df_p = df_daily_grp[df_daily_grp['Producto'] == prod]
                    ax_line.plot(df_p['Fecha_DT'], df_p['PH_Wiidem'], marker='o', label=str(prod)[:25])

                ax_line.set_ylabel("Piezas / Hora (PH Wiidem)")
                fechas_unicas_web = sorted(df_daily_grp['Fecha_DT'].unique())
                ax_line.set_xticks(fechas_unicas_web)
                ax_line.set_xticklabels([pd.to_datetime(x).strftime('%d/%m/%Y') for x in fechas_unicas_web], rotation=45, ha='right')
                ax_line.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
                ax_line.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig_line)
                
                st.markdown("#### 4. Detalle Diario (Día a Día)")
                df_diario_ui = df_daily_grp.copy()
                df_diario_ui['Performance Wiidem (%)'] = np.where(df_diario_ui['PH_Est'] > 0, (df_diario_ui['PH_Wiidem'] / df_diario_ui['PH_Est']) * 100, 0)
                df_diario_ui['Fecha'] = df_diario_ui['Fecha_DT'].dt.strftime('%d/%m/%Y')
                
                df_diario_ui.rename(columns={'Pzas_Prod': 'Piezas Wiidem', 'TC': 'TC Ingenieria', 'PH_Wiidem': 'PH Wiidem'}, inplace=True)

                tabla_diaria = df_diario_ui[['Fecha', 'Producto', 'Tiempo_Hs', 'Piezas Wiidem', 'TC Ingenieria', 'PH Wiidem', 'PH_Est', 'Performance Wiidem (%)']].iloc[::-1].reset_index(drop=True)
                
                st.info("💡 Si deseas editar los objetivos de cadencia, ve a la pestaña **'🛠️ Editor Masivo de Cadencias'**.")
                st.dataframe(
                    tabla_diaria.style.format({
                        'Tiempo_Hs': '{:.2f}', 'Piezas Wiidem': '{:,.0f}', 'TC Ingenieria': '{:.4f}',
                        'PH Wiidem': '{:.1f}', 'PH_Est': '{:.1f}', 'Performance Wiidem (%)': '{:.1f}%'
                    }).background_gradient(subset=['Performance Wiidem (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )

        # =====================================================================
        # PESTAÑA 3: EDITOR MASIVO DE CADENCIAS (NUEVO)
        # =====================================================================
        with tab3:
            st.markdown("### 🛠️ Editor Consolidado de Piezas por Hora")
            st.write("En esta tabla puedes ver **todas las máquinas y todos los días**. Utiliza los filtros de las columnas (ícono de lupa) para buscar una máquina o día específico. Al modificar la columna ✏️ **'PH Objetivo (Editable)'**, el sistema recalculará el Tiempo de Ciclo y la Performance en todas las vistas y reportes PDF.")
            
            # Preparamos los datos para el editor global
            df_edit_global = df_daily_prod.copy()
            df_edit_global['Fecha'] = pd.to_datetime(df_edit_global['Fecha_Str']).dt.strftime('%d/%m/%Y')
            df_edit_global['Tiempo_Hs'] = df_edit_global['Tiempo_Min'] / 60.0
            df_edit_global['PH Wiidem'] = np.where(df_edit_global['Tiempo_Hs'] > 0, df_edit_global['Pzas_Prod'] / df_edit_global['Tiempo_Hs'], 0)
            df_edit_global['PH_Est'] = np.where(df_edit_global['TC'] > 0, 60 / df_edit_global['TC'], 0)
            df_edit_global['Performance Wiidem (%)'] = np.where(df_edit_global['PH_Est'] > 0, (df_edit_global['PH Wiidem'] / df_edit_global['PH_Est']) * 100, 0)
            
            # Seleccionamos las columnas útiles para la edición masiva
            tabla_masiva = df_edit_global[['Clave_Unica', 'Fecha', 'Máquina', 'Producto', 'Tiempo_Hs', 'Pzas_Prod', 'TC', 'PH Wiidem', 'PH_Est', 'Performance Wiidem (%)']].copy()
            tabla_masiva.rename(columns={'Pzas_Prod': 'Piezas Wiidem', 'TC': 'TC Ingenieria'}, inplace=True)
            
            # Columna editable
            tabla_masiva['PH Objetivo (Editable ✏️)'] = tabla_masiva['PH_Est'].round(1)

            # Mostrar el Data Editor Global
            edited_df_global = st.data_editor(
                tabla_masiva.style.format({
                    'Tiempo_Hs': '{:.2f}', 'Piezas Wiidem': '{:,.0f}', 'TC Ingenieria': '{:.4f}',
                    'PH Wiidem': '{:.1f}', 'PH_Est': '{:.1f}', 'Performance Wiidem (%)': '{:.1f}%',
                    'PH Objetivo (Editable ✏️)': '{:.1f}'
                }).background_gradient(subset=['Performance Wiidem (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                column_config={
                    "Clave_Unica": None, # Ocultamos la clave interna
                    "Fecha": st.column_config.Column(disabled=True),
                    "Máquina": st.column_config.Column(disabled=True),
                    "Producto": st.column_config.Column(disabled=True),
                    "Tiempo_Hs": st.column_config.NumberColumn(disabled=True),
                    "Piezas Wiidem": st.column_config.NumberColumn(disabled=True),
                    "TC Ingenieria": st.column_config.NumberColumn(disabled=True),
                    "PH Wiidem": st.column_config.NumberColumn(disabled=True),
                    "PH_Est": st.column_config.NumberColumn(disabled=True),
                    "Performance Wiidem (%)": st.column_config.NumberColumn(disabled=True),
                    "PH Objetivo (Editable ✏️)": st.column_config.NumberColumn(
                        "PH Objetivo (Editable ✏️)",
                        help="Cambia este valor y presiona Enter para recalcular todo.",
                        min_value=0.1, step=1.0
                    )
                },
                use_container_width=True, 
                hide_index=True,
                key="editor_masivo_global"
            )

            # Detectar cambios en la tabla masiva
            cambios_realizados = False
            for index, row in edited_df_global.iterrows():
                val_actual = row['PH Objetivo (Editable ✏️)']
                val_original = row['PH_Est']
                clave = row['Clave_Unica']
                
                # Si el valor actual es diferente al original (con tolerancia a decimales)
                if abs(val_actual - val_original) > 0.1:
                    if st.session_state["correcciones_cadencia"].get(clave) != val_actual:
                        st.session_state["correcciones_cadencia"][clave] = val_actual
                        cambios_realizados = True

            if cambios_realizados:
                st.success("✅ Cambios guardados. Recalculando datos para los reportes y gráficas...")
                st.rerun()

        # =====================================================================
        # PESTAÑA 2: MENÚ DE EXPORTACIÓN A PDF
        # =====================================================================
        with tab2:
            st.markdown("### 📄 Configuración de Reportes PDF")
            st.info("💡 **Nota:** Los reportes PDF se generarán aplicando todas las correcciones que hayas realizado en el **Editor Masivo**.")
            
            opcion_reporte = st.radio(
                "Selecciona qué reporte deseas generar:", 
                ["1. Reporte General (Torta, Producto y Operario)", 
                 "2. Reporte Evolutivo Diario (Gráfico de Líneas)", 
                 "3. Generar AMBOS"]
            )

            incluir_op = False
            if "1" in opcion_reporte or "3" in opcion_reporte:
                incluir_op = st.checkbox("Incluir detalle de OPERARIOS en el Reporte General", value=True)

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
                    
                    if ("1" in opcion_reporte or "3" in opcion_reporte) and not df_global.empty:
                        maqs_general = sorted(df_global['Máquina'].unique())
                        res_gen = generar_pdf_produccion(maqs_general, df_global, df_productos, df_operarios, incluir_op, intervalo_str)
                        
                        if res_gen and os.path.exists(res_gen):
                            st.success(f"✅ Reporte General Generado.")
                            with open(res_gen, "rb") as f:
                                st.download_button(
                                    label="📥 Descargar Reporte General (.pdf)", 
                                    data=f, 
                                    file_name=res_gen, 
                                    mime="application/pdf"
                                )
                    
                    if ("2" in opcion_reporte or "3" in opcion_reporte) and maquinas_a_procesar:
                        # Pasamos df_daily_prod que YA TIENE las correcciones de TC inyectadas
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
