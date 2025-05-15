import streamlit as st
import psycopg2
import os
import qrcode
from PIL import Image
from io import BytesIO
import time
from urllib.parse import urlparse
from datetime import timedelta

# Configuración inicial
st.set_page_config(page_title="Sistema de Asistencia con QR", layout="wide")
os.makedirs("qr_codes", exist_ok=True)

# ==============================================
# CONEXIÓN A POSTGRESQL (PRODUCCIÓN)
# ==============================================
def get_db_connection():
    db_url = "postgresql://admin_asistencia:Bd5tYJfzE1pNoASHMyUStull4tJpyYLc@dpg-d0j29p2li9vc73bevkpg-a.oregon-postgres.render.com/asistencia_qr"
    
    parsed_url = urlparse(db_url)
    conn = psycopg2.connect(
        database=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port,
        sslmode='require'
    )
    return conn

# ==============================================
# INICIALIZACIÓN DE LA BASE DE DATOS
# ==============================================
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Tabla de usuarios
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                    (id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE,
                    password TEXT,
                    nombre TEXT,
                    tipo TEXT CHECK(tipo IN ('admin', 'profesor', 'alumno')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Tabla de clases
        c.execute('''CREATE TABLE IF NOT EXISTS clases
                    (id SERIAL PRIMARY KEY,
                    nombre TEXT UNIQUE,
                    profesor_id INTEGER REFERENCES usuarios(id),
                    qr_token TEXT,
                    activa BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Tabla de asistencias
        c.execute('''CREATE TABLE IF NOT EXISTS asistencias
                    (id SERIAL PRIMARY KEY,
                    estudiante_id INTEGER REFERENCES usuarios(id),
                    clase_id INTEGER REFERENCES clases(id),
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Tabla alumnos_clases
        c.execute('''CREATE TABLE IF NOT EXISTS alumnos_clases
                    (alumno_id INTEGER REFERENCES usuarios(id),
                    clase_id INTEGER REFERENCES clases(id),
                    PRIMARY KEY (alumno_id, clase_id))''')
        
        # Crear usuario admin si no existe
        c.execute("SELECT 1 FROM usuarios WHERE username='admin'")
        if not c.fetchone():
            c.execute("INSERT INTO usuarios (username, password, nombre, tipo) VALUES (%s, %s, %s, %s)",
                     ('admin', 'admin123', 'Administrador', 'admin'))
        
        conn.commit()
    except Exception as e:
        st.error(f"Error inicializando la base de datos: {str(e)}")
    finally:
        conn.close()

init_db()

# ==============================================
# FUNCIONES AUXILIARES
# ==============================================
def generar_qr(url, filename=None):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    if filename:
        img.save(f"qr_codes/{filename}")
    return img

def img_to_bytes(img):
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return buffered.getvalue()

def generar_url_qr(clase_id, qr_token):
    return f"https://asistenciaqr.onrender.com/?clase_id={clase_id}&token={qr_token}"

# ==============================================
# AUTENTICACIÓN
# ==============================================
def login():
    st.sidebar.title("Inicio de Sesión")
    username = st.sidebar.text_input("Usuario")
    password = st.sidebar.text_input("Contraseña", type="password")
    
    if st.sidebar.button("Ingresar"):
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, username, nombre, tipo FROM usuarios WHERE username = %s AND password = %s",
                (username, password)
            )
            user = c.fetchone()
            
            if user:
                st.session_state.user = {
                    'id': user[0],
                    'username': user[1],
                    'nombre': user[2],
                    'tipo': user[3]
                }
                st.rerun()
            else:
                st.sidebar.error("Usuario o contraseña incorrectos")
        finally:
            conn.close()

def logout():
    if 'user' in st.session_state:
        del st.session_state.user
    st.rerun()

# ==============================================
# VISTAS
# ==============================================
def vista_admin():
    st.title("Panel de Administración")
    
    tab1, tab2, tab3 = st.tabs(["Clases", "Profesores", "Alumnos"])
    
    with tab1:
        st.header("Gestión de Clases")
        
        with st.expander("Crear Nueva Clase", expanded=False):
            with st.form("nueva_clase"):
                nombre = st.text_input("Nombre de la clase (debe ser único)")
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT id, nombre FROM usuarios WHERE tipo = 'profesor'")
                profesores = c.fetchall()
                conn.close()
                
                if profesores:
                    profesor_id = st.selectbox(
                        "Profesor",
                        options=[p[0] for p in profesores],
                        format_func=lambda x: next(p[1] for p in profesores if p[0] == x)
                    )
                    
                    if st.form_submit_button("Crear Clase"):
                        qr_token = os.urandom(16).hex()
                        conn = get_db_connection()
                        try:
                            c = conn.cursor()
                            c.execute(
                                "INSERT INTO clases (nombre, profesor_id, qr_token) VALUES (%s, %s, %s) RETURNING id",
                                (nombre, profesor_id, qr_token)
                            )
                            clase_id = c.fetchone()[0]
                            conn.commit()
                            
                            url = generar_url_qr(clase_id, qr_token)
                            qr_img = generar_qr(url, f"clase_{clase_id}.png")
                            
                            st.success("Clase creada exitosamente!")
                            st.image(img_to_bytes(qr_img), caption=f"QR para {nombre}", width=300)
                            st.code(url)
                        except psycopg2.IntegrityError:
                            st.error("Ya existe una clase con ese nombre")
                        finally:
                            conn.close()
                else:
                    st.warning("No hay profesores registrados. Registra al menos un profesor primero.")
        
        st.subheader("Clases Existentes")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """SELECT c.id, c.nombre, u.nombre as profesor, c.activa, c.created_at 
            FROM clases c 
            JOIN usuarios u ON c.profesor_id = u.id 
            ORDER BY c.activa DESC, c.created_at DESC"""
        )
        clases = c.fetchall()
        conn.close()
        
        if clases:
            for clase in clases:
                with st.expander(f"{clase[1]} {'(Activa)' if clase[3] else '(Inactiva)'} - Profesor: {clase[2]}"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT qr_token FROM clases WHERE id = %s", (clase[0],))
                        qr_token = c.fetchone()[0]
                        conn.close()
                        
                        url = generar_url_qr(clase[0], qr_token)
                        st.image(img_to_bytes(generar_qr(url)), caption=f"QR para {clase[1]}", width=250)
                        st.code(url)
                        
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT COUNT(*) FROM alumnos_clases WHERE clase_id = %s", (clase[0],))
                        num_alumnos = c.fetchone()[0]
                        c.execute("SELECT COUNT(*) FROM asistencias WHERE clase_id = %s", (clase[0],))
                        num_asistencias = c.fetchone()[0]
                        conn.close()
                        
                        st.write(f"Alumnos inscritos: {num_alumnos}")
                        st.write(f"Asistencias registradas: {num_asistencias}")
                    
                    with col2:
                        with st.form(f"opciones_clase_{clase[0]}"):
                            nueva_activa = not clase[3]
                            if st.form_submit_button("Activar" if nueva_activa else "Desactivar"):
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute(
                                    "UPDATE clases SET activa = %s WHERE id = %s",
                                    (nueva_activa, clase[0])
                                )
                                conn.commit()
                                conn.close()
                                st.rerun()
                            
                            if st.form_submit_button("Regenerar QR"):
                                nuevo_token = os.urandom(16).hex()
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute(
                                    "UPDATE clases SET qr_token = %s WHERE id = %s",
                                    (nuevo_token, clase[0])
                                )
                                conn.commit()
                                conn.close()
                                st.rerun()
        else:
            st.info("No hay clases registradas aún")

    with tab2:
        st.header("Gestión de Profesores")
        
        with st.expander("Registrar Nuevo Profesor", expanded=False):
            with st.form("nuevo_profesor"):
                username = st.text_input("Usuario (único)")
                nombre = st.text_input("Nombre completo")
                password = st.text_input("Contraseña", type="password")
                
                if st.form_submit_button("Registrar Profesor"):
                    conn = get_db_connection()
                    try:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO usuarios (username, password, nombre, tipo) VALUES (%s, %s, %s, %s)",
                            (username, password, nombre, 'profesor')
                        )
                        conn.commit()
                        st.success("Profesor registrado exitosamente!")
                    except psycopg2.IntegrityError:
                        st.error("El nombre de usuario ya existe")
                    finally:
                        conn.close()
        
        st.subheader("Listado de Profesores")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, nombre, created_at FROM usuarios WHERE tipo = 'profesor' ORDER BY nombre")
        profesores = c.fetchall()
        conn.close()
        
        if profesores:
            for profesor in profesores:
                with st.expander(f"{profesor[2]} (Usuario: {profesor[1]})"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Registrado el:** {profesor[3]}")
                        
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT id, nombre FROM clases WHERE profesor_id = %s", (profesor[0],))
                        clases = c.fetchall()
                        conn.close()
                        
                        if clases:
                            st.write("**Clases asignadas:**")
                            for clase in clases:
                                st.write(f"- {clase[1]}")
                        else:
                            st.write("No tiene clases asignadas")
                    
                    with col2:
                        with st.form(f"eliminar_profesor_{profesor[0]}"):
                            if st.form_submit_button("Eliminar Profesor"):
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute("SELECT 1 FROM clases WHERE profesor_id = %s", (profesor[0],))
                                tiene_clases = c.fetchone()
                                
                                if not tiene_clases:
                                    c.execute("DELETE FROM usuarios WHERE id = %s", (profesor[0],))
                                    conn.commit()
                                    st.success("Profesor eliminado correctamente")
                                    st.rerun()
                                else:
                                    st.error("No se puede eliminar: tiene clases asignadas")
                                conn.close()
        else:
            st.info("No hay profesores registrados")

    with tab3:
        st.header("Gestión de Alumnos")
        
        with st.expander("Registrar Nuevo Alumno", expanded=False):
            with st.form("nuevo_alumno"):
                username = st.text_input("Usuario (único)")
                nombre = st.text_input("Nombre completo")
                password = st.text_input("Contraseña", type="password")
                
                if st.form_submit_button("Registrar Alumno"):
                    conn = get_db_connection()
                    try:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO usuarios (username, password, nombre, tipo) VALUES (%s, %s, %s, %s)",
                            (username, password, nombre, 'alumno')
                        )
                        conn.commit()
                        st.success("Alumno registrado exitosamente!")
                    except psycopg2.IntegrityError:
                        st.error("El nombre de usuario ya existe")
                    finally:
                        conn.close()
        
        with st.expander("Inscribir Alumno a Clase", expanded=False):
            with st.form("inscribir_alumno"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT id, nombre FROM usuarios WHERE tipo = 'alumno' ORDER BY nombre")
                alumnos = c.fetchall()
                c.execute("SELECT id, nombre FROM clases ORDER BY nombre")
                clases = c.fetchall()
                conn.close()
                
                if alumnos and clases:
                    alumno_id = st.selectbox(
                        "Alumno",
                        options=[a[0] for a in alumnos],
                        format_func=lambda x: next(a[1] for a in alumnos if a[0] == x)
                    )
                    
                    clase_id = st.selectbox(
                        "Clase",
                        options=[c[0] for c in clases],
                        format_func=lambda x: next(c[1] for c in clases if c[0] == x)
                    )
                    
                    if st.form_submit_button("Inscribir Alumno"):
                        conn = get_db_connection()
                        try:
                            c = conn.cursor()
                            c.execute(
                                "INSERT INTO alumnos_clases (alumno_id, clase_id) VALUES (%s, %s)",
                                (alumno_id, clase_id)
                            )
                            conn.commit()
                            st.success("Alumno inscrito exitosamente!")
                        except psycopg2.IntegrityError:
                            st.error("Este alumno ya está inscrito en esta clase")
                        finally:
                            conn.close()
                else:
                    st.warning("Necesitas tener al menos un alumno y una clase creada")
        
        st.subheader("Listado de Alumnos")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, nombre, created_at FROM usuarios WHERE tipo = 'alumno' ORDER BY nombre")
        alumnos = c.fetchall()
        conn.close()
        
        if alumnos:
            for alumno in alumnos:
                with st.expander(f"{alumno[2]} (Usuario: {alumno[1]})"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Registrado el:** {alumno[3]}")
                        
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute(
                            """SELECT c.id, c.nombre 
                            FROM alumnos_clases ac 
                            JOIN clases c ON ac.clase_id = c.id 
                            WHERE ac.alumno_id = %s""",
                            (alumno[0],)
                        )
                        clases = c.fetchall()
                        conn.close()
                        
                        if clases:
                            st.write("**Clases inscritas:**")
                            for clase in clases:
                                st.write(f"- {clase[1]}")
                        else:
                            st.write("No está inscrito en ninguna clase")
                    
                    with col2:
                        with st.form(f"eliminar_alumno_{alumno[0]}"):
                            if st.form_submit_button("Eliminar Alumno"):
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute("DELETE FROM usuarios WHERE id = %s", (alumno[0],))
                                c.execute("DELETE FROM alumnos_clases WHERE alumno_id = %s", (alumno[0],))
                                c.execute("DELETE FROM asistencias WHERE estudiante_id = %s", (alumno[0],))
                                conn.commit()
                                conn.close()
                                st.success("Alumno eliminado correctamente")
                                st.rerun()
        else:
            st.info("No hay alumnos registrados")

def vista_profesor():
    st.title("Panel del Profesor")
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """SELECT c.id, c.nombre, c.activa, c.created_at 
        FROM clases c 
        WHERE c.profesor_id = %s 
        ORDER BY c.activa DESC, c.created_at DESC""",
        (st.session_state.user['id'],)
    )
    clases = c.fetchall()
    conn.close()
    
    if clases:
        for clase in clases:
            with st.expander(f"{clase[1]} {'(Activa)' if clase[2] else '(Inactiva)'}"):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT qr_token FROM clases WHERE id = %s", (clase[0],))
                    qr_token = c.fetchone()[0]
                    conn.close()
                    
                    url = generar_url_qr(clase[0], qr_token)
                    st.image(img_to_bytes(generar_qr(url)), caption=f"QR para {clase[1]}", width=250)
                    st.code(url)
                    
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM alumnos_clases WHERE clase_id = %s", (clase[0],))
                    num_alumnos = c.fetchone()[0]
                    c.execute("SELECT COUNT(*) FROM asistencias WHERE clase_id = %s", (clase[0],))
                    num_asistencias = c.fetchone()[0]
                    conn.close()
                    
                    st.write(f"Alumnos inscritos: {num_alumnos}")
                    st.write(f"Asistencias registradas: {num_asistencias}")
                
                with col2:
                    with st.form(f"opciones_clase_{clase[0]}"):
                        nueva_activa = not clase[2]
                        if st.form_submit_button("Activar" if nueva_activa else "Desactivar"):
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute(
                                "UPDATE clases SET activa = %s WHERE id = %s",
                                (nueva_activa, clase[0])
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()
        
                # Sección mejorada de alumnos y asistencias
                st.subheader(f"📊 Asistencias para {clase[1]}")
                
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("""
                    SELECT u.id, u.nombre, COUNT(a.id) as total_asistencias
                    FROM alumnos_clases ac
                    JOIN usuarios u ON ac.alumno_id = u.id
                    LEFT JOIN asistencias a ON a.estudiante_id = u.id AND a.clase_id = %s
                    WHERE ac.clase_id = %s
                    GROUP BY u.id, u.nombre
                    ORDER BY u.nombre
                """, (clase[0], clase[0]))
                alumnos_asistencias = c.fetchall()
                conn.close()

                if alumnos_asistencias:
                    for alumno_id, alumno_nombre, total in alumnos_asistencias:
                        # Reemplazamos el expander interno por un contenedor diferente
                        with st.container():
                            st.markdown(f"#### 👤 {alumno_nombre} - {total} asistencia(s)")
                            
                            # Mostrar fechas específicas de asistencia
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("""
                                SELECT fecha FROM asistencias
                                WHERE estudiante_id = %s AND clase_id = %s
                                ORDER BY fecha DESC
                            """, (alumno_id, clase[0]))
                            fechas = c.fetchall()
                            conn.close()

                            if fechas:
                                st.write("**Fechas de asistencia:**")
                                for fecha in fechas:
                                    st.write(f"- {fecha[0].strftime('%Y-%m-%d %H:%M:%S')}")
                                
                                # Opción para filtrar por fecha
                                st.subheader("Filtrar por fecha")
                                col_f1, col_f2 = st.columns(2)
                                with col_f1:
                                    fecha_inicio = st.date_input("Fecha inicio", value=None, key=f"ini_{alumno_id}_{clase[0]}")
                                with col_f2:
                                    fecha_fin = st.date_input("Fecha fin", value=None, key=f"fin_{alumno_id}_{clase[0]}")

                                if fecha_inicio or fecha_fin:
                                    conn = get_db_connection()
                                    c = conn.cursor()
                                    query = """
                                        SELECT fecha FROM asistencias
                                        WHERE estudiante_id = %s AND clase_id = %s
                                    """
                                    params = [alumno_id, clase[0]]
                                    
                                    if fecha_inicio:
                                        query += " AND fecha >= %s"
                                        params.append(fecha_inicio)
                                    if fecha_fin:
                                        query += " AND fecha <= %s"
                                        params.append(fecha_fin + timedelta(days=1))
                                    
                                    query += " ORDER BY fecha DESC"
                                    c.execute(query, tuple(params))
                                    fechas_filtradas = c.fetchall()
                                    conn.close()

                                    st.write("**Asistencias filtradas:**")
                                    if fechas_filtradas:
                                        for fecha in fechas_filtradas:
                                            st.write(f"- {fecha[0].strftime('%Y-%m-%d %H:%M:%S')}")
                                    else:
                                        st.info("No hay asistencias en el rango de fechas seleccionado")
                            else:
                                st.info("No hay registros de asistencia para este alumno")
                else:
                    st.info("No hay alumnos inscritos en esta clase")
    else:
        st.info("No tienes clases asignadas")

def vista_alumno():
    st.title("Panel del Alumno")
    st.write(f"Bienvenido/a {st.session_state.user['nombre']}")
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """SELECT c.id, c.nombre, u.nombre as profesor 
        FROM alumnos_clases ac 
        JOIN clases c ON ac.clase_id = c.id 
        JOIN usuarios u ON c.profesor_id = u.id 
        WHERE ac.alumno_id = %s""",
        (st.session_state.user['id'],)
    )
    clases = c.fetchall()
    conn.close()
    
    if clases:
        st.subheader("Tus Clases")
        for clase in clases:
            with st.expander(f"{clase[1]} - Profesor: {clase[2]}"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    "SELECT fecha FROM asistencias WHERE estudiante_id = %s AND clase_id = %s ORDER BY fecha DESC",
                    (st.session_state.user['id'], clase[0])
                )
                asistencias = c.fetchall()
                conn.close()
                
                if asistencias:
                    st.write("**Tus asistencias:**")
                    for asistencia in asistencias:
                        st.write(f"- {asistencia[0]}")
                else:
                    st.info("No has registrado asistencias en esta clase")
    else:
        st.info("No estás inscrito en ninguna clase")

def registrar_asistencia():
    st.title("Registro de Asistencia")

    # Obtener parámetros desde la URL
    try:
        params = st.query_params
    except:
        params = {}

    # Modo seguro para extraer los parámetros
    clase_id_str = params["clase_id"] if "clase_id" in params else None
    token = params["token"] if "token" in params else None

    if isinstance(clase_id_str, list):
        clase_id_str = clase_id_str[0]
    if isinstance(token, list):
        token = token[0]

    # Validaciones básicas
    if not clase_id_str or not token:
        st.error("⚠️ URL inválida. Asegúrate de escanear el código QR correcto.")
        return

    try:
        clase_id = int(clase_id_str)
    except ValueError:
        st.error("⚠️ El ID de la clase no es válido.")
        return

    # Verificar sesión activa
    if 'user' not in st.session_state:
        st.warning("🔒 Debes iniciar sesión como alumno para registrar asistencia.")
        login()
        return

    if st.session_state.user['tipo'] != 'alumno':
        st.error("⛔ Solo los alumnos pueden registrar asistencia.")
        return

    # Conexión y validación de clase
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, nombre, activa FROM clases WHERE id = %s AND qr_token = %s",
            (clase_id, token)
        )
        clase = c.fetchone()

        if not clase:
            st.error("""❌ Clase no encontrada. Verifica:
- Que estás usando el código QR más reciente
- Que la clase no ha sido eliminada
- Que el enlace contiene correctamente los parámetros `clase_id` y `token`""")
            return

        if not clase[2]:
            st.warning("⚠️ Esta clase está actualmente desactivada.")
            return

        # Verificar inscripción del alumno
        c.execute(
            "SELECT 1 FROM alumnos_clases WHERE alumno_id = %s AND clase_id = %s",
            (st.session_state.user['id'], clase[0])
        )
        if not c.fetchone():
            st.error("🚫 No estás inscrito en esta clase. No puedes registrar asistencia.")
            return

        # Verificar si ya registró asistencia HOY
        hoy = time.strftime("%Y-%m-%d")  # Fecha en formato YYYY-MM-DD
        c.execute(
            "SELECT 1 FROM asistencias WHERE estudiante_id = %s AND clase_id = %s AND fecha::date = %s::date",
            (st.session_state.user['id'], clase[0], hoy)
        )
        if c.fetchone():
            st.warning("📌 Ya registraste asistencia para esta clase hoy.")
            return

        # Registrar asistencia
        if st.button("✅ Confirmar mi asistencia"):
            c.execute(
                "INSERT INTO asistencias (estudiante_id, clase_id) VALUES (%s, %s)",
                (st.session_state.user['id'], clase[0])
            )
            conn.commit()
            st.balloons()
            st.success(f"🎉 Asistencia registrada exitosamente para {clase[1]}")
            time.sleep(2)
            st.rerun()

    except Exception as e:
        st.error(f"🐘 Error al registrar asistencia: {e}")
    finally:
        conn.close()

def main():
    # Obtener parámetros de la URL (compatible con todas versiones)
    try:
        params = st.query_params
    except:
        params = {}
    
    if "clase_id" in params:
        registrar_asistencia()
        return
    
    if 'user' not in st.session_state:
        login()
    else:
        st.sidebar.title(f"Bienvenid@, {st.session_state.user['nombre']}")
        st.sidebar.button("Cerrar Sesión", on_click=logout)
        
        if st.session_state.user['tipo'] == 'admin':
            vista_admin()
        elif st.session_state.user['tipo'] == 'profesor':
            vista_profesor()
        elif st.session_state.user['tipo'] == 'alumno':
            vista_alumno()

if __name__ == "__main__":
    main()