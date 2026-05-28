import streamlit as st
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# Configuración de la página de Streamlit
st.set_page_config(
    page_title="Logística del Pacífico S.A. - Ruteo",
    page_icon="🚚",
    layout="wide"
)

# Inicializar geolocalizador gratuito (OpenStreetMap - Nominatim)
@st.cache_resource
def obtener_geolocalizador():
    return Nominatim(user_agent="logistica_pacifico_routing_app_v1")

geolocator = obtener_geolocalizador()

# Función para buscar coordenadas por dirección o nombre de lugar
def buscar_coordenadas(direccion):
    try:
        location = geolocator.geocode(direccion, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
        return None
    except GeocoderTimedOut:
        return "timeout"
    except Exception:
        return None

# Función de distancia euclídea aproximada (tal como estaba en el notebook)
def calcular_distancia_euclidiana(coord1, coord2):
    lat1, lon1 = coord1[0], coord1[1]
    lat2, lon2 = coord2[0], coord2[1]
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    distancia_grados = math.sqrt(delta_lat**2 + delta_lon**2)
    distancia_metros = distancia_grados * 111000
    return int(distancia_metros)

# Fórmula alternativa más exacta (Haversine)
def calcular_distancia_haversine(coord1, coord2):
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(6371000 * c) # Retorna metros utilizando el radio de la tierra

# --- INTERFAZ DE STREAMLIT ---
st.title("🚚 Optimización de Ruteo de Vehículos (CVRP)")
st.subheader("Logística del Pacífico S.A. — Planificador Inteligente")

st.markdown("""
Esta aplicación permite diseñar y optimizar rutas de distribución con restricciones de capacidad (CVRP) utilizando **Google OR-Tools**. 
Puedes buscar ubicaciones por su nombre o dirección, ajustar demandas de clientes, capacidades de la flota y ver la simulación en un mapa interactivo.
""")

# Crear pestañas para organizar la interfaz
tab_datos, tab_resultados = st.tabs(["📊 Configuración de Datos", "🏁 Ejecutar Optimización"])

with tab_datos:
    col_cedi, col_flota = st.columns([2, 1])
    
    with col_cedi:
        st.header("📍 1. Centro de Distribución (CEDI / Depósito)")
        cedi_busqueda = st.text_input("Buscar dirección/lugar del CEDI:", "Acopi, Yumbo, Colombia")
        
        # Estado de sesión para almacenar coordenadas del CEDI
        if 'cedi_lat' not in st.session_state:
            st.session_state.cedi_lat = 3.518
            st.session_state.cedi_lon = -76.510
            st.session_state.cedi_nombre = "CEDI Acopi (Yumbo)"
            
        if st.button("🔍 Buscar CEDI"):
            res = buscar_coordenadas(cedi_busqueda)
            if res == "timeout":
                st.warning("La búsqueda tardó demasiado. Inténtalo de nuevo.")
            elif res:
                st.session_state.cedi_lat, st.session_state.cedi_lon, direccion_completa = res
                st.session_state.cedi_nombre = cedi_busqueda
                st.success(f"Ubicación encontrada: {direccion_completa}")
            else:
                st.error("No se encontró el lugar. Revisa la ortografía o ingresa las coordenadas manualmente abajo.")
                
        # Inputs manuales de coordenadas por si falla el buscador
        col_c1, col_c2 = st.columns(2)
        st.session_state.cedi_nombre = col_c1.text_input("Nombre de CEDI:", st.session_state.cedi_nombre)
        st.session_state.cedi_lat = col_c2.number_input("Latitud CEDI:", value=st.session_state.cedi_lat, format="%.6f")
        st.session_state.cedi_lon = col_c2.number_input("Longitud CEDI:", value=st.session_state.cedi_lon, format="%.6f")

    with col_flota:
        st.header("🚚 2. Configuración de Flota")
        num_vehiculos = st.number_input("Número de camiones disponibles:", min_value=1, max_value=20, value=3)
        capacidad_vehiculo = st.number_input("Capacidad de carga por furgón (kg):", min_value=100, max_value=50000, value=3000)
        
        # Parámetros del algoritmo
        st.subheader("⚙️ Parámetros Avanzados")
        tipo_distancia = st.selectbox(
            "Método de cálculo de distancia:",
            ["Euclídea Aproximada (Fórmula Original)", "Haversine (Precisión de curvatura real)"]
        )
        limite_tiempo = st.slider("Límite de tiempo de cómputo (segundos):", 1, 10, 2)

    st.write("---")
    st.header("👥 3. Gestión de Clientes")
    st.markdown("Busca y añade un cliente, o edita la tabla dinámica interactiva directamente al final:")

    # Buscador de clientes
    col_busc_cli, col_dem_cli = st.columns([3, 1])
    cli_busqueda = col_busc_cli.text_input("Buscar dirección/lugar del Cliente a añadir:", "Chipichape, Cali, Colombia")
    cli_demanda = col_dem_cli.number_input("Demanda del cliente (kg):", min_value=1, max_value=10000, value=1000)
    
    # Inicializar estado de sesión de clientes por defecto (con los datos originales de Cali)
    if 'tabla_clientes' not in st.session_state:
        st.session_state.tabla_clientes = pd.DataFrame({
            'Nombre': [
                "Chipichape (Norte)", 
                "El Peñón (Oeste)", 
                "Plaza de Cayzedo (Centro)", 
                "Unicentro (Sur)", 
                "Ciudad 2000 (Sur-Oriente)"
            ],
            'Latitud': [3.476, 3.452, 3.451, 3.376, 3.398],
            'Longitud': [-76.527, -76.541, -76.532, -76.537, -76.515],
            'Demanda_kg': [1200, 800, 1500, 2000, 1000]
        })

    if st.button("➕ Buscar y Añadir Cliente"):
        res_cli = buscar_coordenadas(cli_busqueda)
        if res_cli == "timeout":
            st.warning("La búsqueda tardó demasiado. Inténtalo de nuevo.")
        elif res_cli:
            lat_c, lon_c, direccion_c = res_cli
            # Crear nueva fila
            nueva_fila = pd.DataFrame({
                'Nombre': [cli_busqueda],
                'Latitud': [lat_c],
                'Longitud': [lon_c],
                'Demanda_kg': [cli_demanda]
            })
            # Concatenar a la sesión
            st.session_state.tabla_clientes = pd.concat([st.session_state.tabla_clientes, nueva_fila], ignore_index=True)
            st.success(f"Cliente añadido correctamente: {direccion_c}")
        else:
            st.error("No se encontró el lugar. Puedes agregarlo escribiendo directamente en la última fila de la tabla de abajo.")

    # Mostrar la tabla de clientes editable
    st.subheader("✏️ Tabla Interactiva de Clientes")
    st.markdown("Puedes hacer doble clic en cualquier celda para editar sus datos. También puedes marcar filas y presionar la tecla `Supr` o hacer clic en el ícono de papelera para eliminarlas. Para añadir un cliente manual usa la última fila vacía.")
    
    # Editor de datos nativo de Streamlit
    clientes_editados = st.data_editor(
        st.session_state.tabla_clientes,
        num_rows="dynamic",
        key="editor_clientes",
        column_config={
            "Nombre": st.column_config.TextColumn("Nombre/Identificador del Cliente", required=True),
            "Latitud": st.column_config.NumberColumn("Latitud", format="%.6f", min_value=-90.0, max_value=90.0),
            "Longitud": st.column_config.NumberColumn("Longitud", format="%.6f", min_value=-180.0, max_value=180.0),
            "Demanda_kg": st.column_config.NumberColumn("Demanda (Kilogramos)", min_value=0, step=10)
        }
    )
    
    # Actualizar estado de la sesión
    st.session_state.tabla_clientes = clientes_editados

with tab_resultados:
    st.header("🏁 Resultados del Algoritmo de Ruteo")
    
    # Validaciones previas de consistencia
    if len(st.session_state.tabla_clientes) == 0:
        st.error("❌ No hay clientes registrados en la tabla de datos.")
    else:
        # Preparación de los datos estructurados para OR-Tools
        coordenadas = [[st.session_state.cedi_lat, st.session_state.cedi_lon]]
        nombres_nodos = [st.session_state.cedi_nombre]
        demandas = [0]
        
        # Limpieza de valores nulos o inválidos de la tabla editada
        df_limpio = st.session_state.tabla_clientes.dropna(subset=['Nombre', 'Latitud', 'Longitud'])
        
        for _, fila in df_limpio.iterrows():
            coordenadas.append([float(fila['Latitud']), float(fila['Longitud'])])
            nombres_nodos.append(str(fila['Nombre']))
            demandas.append(int(fila['Demanda_kg']))
            
        num_puntos = len(coordenadas)
        
        # Calcular matriz de distancias según el método seleccionado
        matriz_distancias = []
        for i in range(num_puntos):
            fila = []
            for j in range(num_puntos):
                if tipo_distancia == "Euclídea Aproximada (Fórmula Original)":
                    dist = calcular_distancia_euclidiana(coordenadas[i], coordenadas[j])
                else:
                    dist = calcular_distancia_haversine(coordenadas[i], coordenadas[j])
                fila.append(dist)
            matriz_distancias.append(fila)
            
        # Parámetros del modelo
        capacidades_vehiculos = [int(capacidad_vehiculo)] * int(num_vehiculos)
        demanda_total = sum(demandas)
        capacidad_total_flota = sum(capacidades_vehiculos)
        
        # Advertencia de sobredemanda antes de ejecutar
        if demanda_total > capacidad_total_flota:
            st.error(f"❌ **Capacidad Insuficiente:** La demanda total de los clientes ({demanda_total:,} kg) excede la capacidad total de tu flota ({capacidad_total_flota:,} kg). Aumenta la capacidad de carga o el número de camiones en la pestaña de Configuración.")
        else:
            st.info(f"📊 Demanda Total: {demanda_total:,} kg | Capacidad de Flota Activa: {capacidad_total_flota:,} kg")
            
            # Ejecución del Algoritmo
            if st.button("🚀 Ejecutar Optimización de Rutas"):
                
                # Inicializar OR-Tools
                manager = pywrapcp.RoutingIndexManager(num_puntos, int(num_vehiculos), 0)
                routing = pywrapcp.RoutingModel(manager)
                
                # Callbacks
                def callback_distancia(desde_index, hacia_index):
                    desde_nodo = manager.IndexToNode(desde_index)
                    hacia_nodo = manager.IndexToNode(hacia_index)
                    return matriz_distancias[desde_nodo][hacia_nodo]
                    
                transit_callback_index = routing.RegisterTransitCallback(callback_distancia)
                routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
                
                def callback_demanda(desde_index):
                    desde_nodo = manager.IndexToNode(desde_index)
                    return demandas[desde_nodo]
                    
                demand_callback_index = routing.RegisterUnaryTransitCallback(callback_demanda)
                
                # Añadir la dimensión de capacidad (CVRP)
                routing.AddDimensionWithVehicleCapacity(
                    demand_callback_index,
                    0,  # Sin holgura
                    capacidades_vehiculos,
                    True,  # Forzar inicio en cero de carga
                    'Capacidad'
                )
                
                # Parámetros de búsqueda
                parametros_busqueda = pywrapcp.DefaultRoutingSearchParameters()
                parametros_busqueda.first_solution_strategy = (
                    routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
                )
                parametros_busqueda.local_search_metaheuristic = (
                    routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
                )
                parametros_busqueda.time_limit.seconds = int(limite_tiempo)
                
                # Resolver
                solucion = routing.SolveWithParameters(parametros_busqueda)
                
                if solucion:
                    # Estructurar la solución
                    rutas_finales = []
                    for id_vehiculo in range(int(num_vehiculos)):
                        ruta_vehiculo = []
                        index = routing.Start(id_vehiculo)
                        distancia_acumulada = 0
                        
                        while not routing.IsEnd(index):
                            nodo_actual = manager.IndexToNode(index)
                            indice_anterior = index
                            index = solucion.Value(routing.NextVar(index))
                            distancia_tramo = routing.GetArcCostForVehicle(indice_anterior, index, id_vehiculo)
                            distancia_acumulada += distancia_tramo
                            
                            ruta_vehiculo.append({
                                'nodo': nodo_actual,
                                'nombre': nombres_nodos[nodo_actual],
                                'coordenadas': coordenadas[nodo_actual],
                                'demanda': demandas[nodo_actual]
                            })
                            
                        nodo_final = manager.IndexToNode(index)
                        ruta_vehiculo.append({
                            'nodo': nodo_final,
                            'nombre': nombres_nodos[nodo_final],
                            'coordenadas': coordenadas[nodo_final],
                            'demanda': demandas[nodo_final]
                        })
                        
                        rutas_finales.append({
                            'id_vehiculo': id_vehiculo + 1,
                            'trayecto': ruta_vehiculo,
                            'distancia_total_m': distancia_acumulada,
                            'capacidad_maxima': capacidades_vehiculos[id_vehiculo]
                        })
                        
                    # Mostrar métricas del consolidado global en Streamlit
                    gran_distancia_total = sum([r['distancia_total_m'] for r in rutas_finales])
                    gran_carga_total = sum([sum([p['demanda'] for p in r['trayecto']]) for r in rutas_finales])
                    
                    st.success("✅ ¡Optimización completada con éxito!")
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("🏁 Distancia Total Combinada", f"{gran_distancia_total / 1000:.2f} Kilómetros")
                    m2.metric("📦 Mercancía Despachada", f"{gran_carga_total:,} Kilogramos")
                    m3.metric("🚛 Flota Solicitada", f"{sum([1 for r in rutas_finales if len(r['trayecto']) > 2]):01d} Vehículos")
                    
                    st.write("---")
                    
                    # Layout para Reporte e Imagen del Mapa en dos columnas
                    col_rep, col_map = st.columns([1, 1])
                    
                    with col_rep:
                        st.subheader("📋 Plan de Ruta Detallado por Camión")
                        for r in rutas_finales:
                            id_v = r['id_vehiculo']
                            trayecto = r['trayecto']
                            distancia_km = r['distancia_total_m'] / 1000
                            cap_max = r['capacidad_maxima']
                            carga_total_vehiculo = sum([p['demanda'] for p in trayecto])
                            eficiencia = (carga_total_vehiculo / cap_max) * 100
                            
                            # Si no se usó el vehículo, se salta la impresión detallada
                            if len(trayecto) <= 2 and carga_total_vehiculo == 0:
                                st.markdown(f"⚪ **Camión {id_v}:** Sin asignación de servicio (No requerido para cubrir la demanda)")
                                continue
                                
                            with st.expander(f"🟢 🚚 Camión {id_v} — {distancia_km:.2f} km — Carga: {carga_total_vehiculo:,} kg / {cap_max:,} kg ({eficiencia:.1f}%)", expanded=True):
                                carga_acumulada = 0
                                tramos_texto = []
                                for i, punto in enumerate(trayecto):
                                    carga_acumulada += punto['demanda']
                                    demanda_str = f" (+{punto['demanda']} kg)" if punto['demanda'] > 0 else ""
                                    tramos_texto.append(f"**{i+1:02d}.** `{punto['nombre']}`{demanda_str}")
                                    if i < len(trayecto) - 1:
                                        tramos_texto.append(f" &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ➔ *Acumulado en furgón:* {carga_acumulada} kg")
                                        
                                st.markdown("\n".join(tramos_texto), unsafe_allow_html=True)
                                
                    with col_map:
                        st.subheader("🗺️ Representación Gráfica de Rutas")
                        
                        # Generación del gráfico de Matplotlib
                        fig, ax = plt.subplots(figsize=(10, 8), dpi=100)
                        colores_rutas = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2']
                        
                        lats = [c[0] for c in coordenadas]
                        lons = [c[1] for c in coordenadas]
                        
                        # Dibujar clientes y CEDI
                        ax.scatter(lons[1:], lats[1:], color='#E67E22', s=180, zorder=5, label='Clientes')
                        ax.scatter(lons[0], lats[0], color='#2C3E50', s=350, marker='H', zorder=6, label='CEDI / Origen')
                        
                        # Dibujar trayectos
                        for idx, r in enumerate(rutas_finales):
                            trayecto = r['trayecto']
                            if len(trayecto) <= 2 and sum([p['demanda'] for p in trayecto]) == 0:
                                continue
                                
                            color = colores_rutas[idx % len(colores_rutas)]
                            ruta_x = [p['coordenadas'][1] for p in trayecto]
                            ruta_y = [p['coordenadas'][0] for p in trayecto]
                            
                            ax.plot(ruta_x, ruta_y, color=color, linestyle='-', linewidth=2.5,
                                     label=f'Ruta Camión {r["id_vehiculo"]} ({r["distancia_total_m"]/1000:.2f} km)', zorder=3)
                            
                            # Añadir flechas indicativas de sentido en la mitad del tramo
                            for i in range(len(trayecto) - 1):
                                x_origen = trayecto[i]['coordenadas'][1]
                                y_origen = trayecto[i]['coordenadas'][0]
                                x_destino = trayecto[i+1]['coordenadas'][1]
                                y_destino = trayecto[i+1]['coordenadas'][0]
                                
                                dx = x_destino - x_origen
                                dy = y_destino - y_origen
                                
                                ax.annotate('', xy=(x_origen + dx*0.55, y_origen + dy*0.55),
                                             xytext=(x_origen + dx*0.45, y_origen + dy*0.45),
                                             arrowprops=dict(arrowstyle="->", color=color, lw=2.5, mutation_scale=15),
                                             zorder=4)
                                
                        # Añadir etiquetas en el mapa
                        for i, nombre in enumerate(nombres_nodos):
                            offset_y = 0.003 if i != 0 else -0.005
                            offset_x = 0.001
                            etiqueta = f"{nombre}\n(+{demandas[i]} kg)" if i != 0 else "🏬 CEDI (Origen)"
                            ax.text(coordenadas[i][1] + offset_x, coordenadas[i][0] + offset_y, etiqueta,
                                     fontsize=8, weight='bold' if i==0 else 'normal',
                                     bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'),
                                     zorder=7)
                                     
                        ax.set_title("MAPA DE DISTRIBUCIÓN Y RUTAS EN TIEMPO REAL", fontsize=11, weight='bold', pad=10)
                        ax.set_xlabel("Longitud", fontsize=9)
                        ax.set_ylabel("Latitud", fontsize=9)
                        ax.grid(True, linestyle='--', alpha=0.5)
                        ax.legend(loc='best', fontsize=8, frameon=True, shadow=True, facecolor='white')
                        
                        plt.tight_layout()
                        
                        # Renderizar figura de Matplotlib en Streamlit
                        st.pyplot(fig)
                        
                else:
                    st.error("❌ No se pudo encontrar una solución de ruteo válida. Comprueba que las capacidades sean suficientes y los parámetros lógicos.")
