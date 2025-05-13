import streamlit as st
import sqlite3
import os
import qrcode
from PIL import Image
from io import BytesIO
import time

# Configuración inicial
st.set_page_config(page_title="Sistema de Asistencia con QR", layout="wide")

# Crear directorios si no existen
os.makedirs("data", exist_ok=True)
os.makedirs("qr_codes", exist_ok=True)

# Inicializar base de datos
def init_db():
    conn = sqlite3.connect('data/database.db')
    c = conn.cursor()
    
    # Tabla de usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE,
                 password TEXT,
                 nombre TEXT,
                 tipo TEXT CHECK(tipo IN ('admin', 'profesor', 'alumno')),
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Tabla de clases
    c.execute('''CREATE TABLE IF NOT EXISTS clases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 nombre TEXT UNIQUE,
                 profesor_id INTEGER,
                 qr_token TEXT,
                 activa BOOLEAN DEFAULT 1,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY (profesor_id) REFERENCES usuarios(id))''')
    
    # Tabla de asistencias
    c.execute('''CREATE TABLE IF NOT EXISTS asistencias
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 estudiante_id INTEGER,
                 clase_id INTEGER,
                 fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY (estudiante_id) REFERENCES usuarios(id),
                 FOREIGN KEY (clase_id) REFERENCES clases(id))''')
    
    # Tabla alumnos_clases
    c.execute('''CREATE TABLE IF NOT EXISTS alumnos_clases
                 (alumno_id INTEGER,
                 clase_id INTEGER,
                 PRIMARY KEY (alumno_id, clase_id),
                 FOREIGN KEY (alumno_id) REFERENCES usuarios(id),
                 FOREIGN KEY (clase_id) REFERENCES clases(id))''')
    
    # Crear usuario admin si no existe
    c.execute("SELECT 1 FROM usuarios WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (username, password, nombre, tipo) VALUES (?, ?, ?, ?)",
                  ('admin', 'admin123', 'Administrador', 'admin'))
    
    conn.commit()
    conn.close()

init_db()

# Funciones de ayuda
def get_db_connection():
    return sqlite3.connect('data/database.db')

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
    return f"/?clase_id={clase_id}&token={qr_token}"

# Autenticación
def login():
    st.sidebar.title("Inicio de Sesión")
    username = st.sidebar.text_input("Usuario")
    password = st.sidebar.text_input("Contraseña", type="password")
    
    if st.sidebar.button("Ingresar"):
        conn = get_db_connection()
        user = conn.execute(
            "SELECT id, username, nombre, tipo FROM usuarios WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        conn.close()
        
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

def logout():
    if 'user' in st.session_state:
        del st.session_state.user
    st.rerun()

# Vistas
def vista_admin():
    st.title("Panel de Administración")
    
    tab1, tab2, tab3 = st.tabs(["Clases", "Profesores", "Alumnos"])
    
    with tab1:
        st.header("Gestión de Clases")
        
        # Crear nueva clase
        with st.expander("Crear Nueva Clase", expanded=False):
            with st.form("nueva_clase"):
                nombre = st.text_input("Nombre de la clase (debe ser único)")
                profesores = get_db_connection().execute(
                    "SELECT id, nombre FROM usuarios WHERE tipo = 'profesor'"
                ).fetchall()
                
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
                            conn.execute(
                                "INSERT INTO clases (nombre, profesor_id, qr_token) VALUES (?, ?, ?)",
                                (nombre, profesor_id, qr_token)
                            )
                            clase_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                            conn.commit()
                            
                            # Generar QR
                            url = generar_url_qr(clase_id, qr_token)
                            qr_img = generar_qr(url, f"clase_{clase_id}.png")
                            
                            st.success("Clase creada exitosamente!")
                            img_bytes = img_to_bytes(qr_img)
                            st.image(img_bytes, caption=f"QR para {nombre}", width=300)
                            st.code(url, language="text")
                        except sqlite3.IntegrityError:
                            st.error("Ya existe una clase con ese nombre")
                        finally:
                            conn.close()
                else:
                    st.warning("No hay profesores registrados. Registra al menos un profesor primero.")
        
        # Gestión de clases existentes
        st.subheader("Clases Existentes")
        conn = get_db_connection()
        clases = conn.execute(
            """SELECT c.id, c.nombre, u.nombre as profesor, c.activa, c.created_at 
            FROM clases c 
            JOIN usuarios u ON c.profesor_id = u.id 
            ORDER BY c.activa DESC, c.created_at DESC"""
        ).fetchall()
        conn.close()
        
        if clases:
            for clase in clases:
                with st.expander(f"{clase[1]} {'(Activa)' if clase[3] else '(Inactiva)'} - Profesor: {clase[2]}"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        # Obtener token QR
                        conn = get_db_connection()
                        qr_token = conn.execute(
                            "SELECT qr_token FROM clases WHERE id = ?",
                            (clase[0],)
                        ).fetchone()[0]
                        conn.close()
                        
                        url = generar_url_qr(clase[0], qr_token)
                        qr_img = generar_qr(url)
                        img_bytes = img_to_bytes(qr_img)
                        
                        st.image(img_bytes, caption=f"QR para {clase[1]}", width=250)
                        st.code(url, language="text")
                        
                        # Estadísticas
                        conn = get_db_connection()
                        num_alumnos = conn.execute(
                            "SELECT COUNT(*) FROM alumnos_clases WHERE clase_id = ?",
                            (clase[0],)
                        ).fetchone()[0]
                        num_asistencias = conn.execute(
                            "SELECT COUNT(*) FROM asistencias WHERE clase_id = ?",
                            (clase[0],)
                        ).fetchone()[0]
                        conn.close()
                        
                        st.write(f"Alumnos inscritos: {num_alumnos}")
                        st.write(f"Asistencias registradas: {num_asistencias}")
                    
                    with col2:
                        # Opciones de gestión
                        with st.form(f"opciones_clase_{clase[0]}"):
                            nueva_activa = not clase[3]
                            if st.form_submit_button("Activar" if nueva_activa else "Desactivar"):
                                conn = get_db_connection()
                                conn.execute(
                                    "UPDATE clases SET activa = ? WHERE id = ?",
                                    (nueva_activa, clase[0])
                                )
                                conn.commit()
                                conn.close()
                                st.rerun()
                            
                            if st.form_submit_button("Regenerar QR"):
                                nuevo_token = os.urandom(16).hex()
                                conn = get_db_connection()
                                conn.execute(
                                    "UPDATE clases SET qr_token = ? WHERE id = ?",
                                    (nuevo_token, clase[0])
                                )
                                conn.commit()
                                conn.close()
                                st.rerun()
        else:
            st.info("No hay clases registradas aún")

    with tab2:
        st.header("Gestión de Profesores")
        
        # Registrar nuevo profesor
        with st.expander("Registrar Nuevo Profesor", expanded=False):
            with st.form("nuevo_profesor"):
                username = st.text_input("Usuario (único)")
                nombre = st.text_input("Nombre completo")
                password = st.text_input("Contraseña", type="password")
                
                if st.form_submit_button("Registrar Profesor"):
                    conn = get_db_connection()
                    try:
                        conn.execute(
                            "INSERT INTO usuarios (username, password, nombre, tipo) VALUES (?, ?, ?, ?)",
                            (username, password, nombre, 'profesor')
                        )
                        conn.commit()
                        st.success("Profesor registrado exitosamente!")
                    except sqlite3.IntegrityError:
                        st.error("El nombre de usuario ya existe")
                    finally:
                        conn.close()
        
        # Listado y gestión de profesores
        st.subheader("Listado de Profesores")
        conn = get_db_connection()
        profesores = conn.execute(
            "SELECT id, username, nombre, created_at FROM usuarios WHERE tipo = 'profesor' ORDER BY nombre"
        ).fetchall()
        conn.close()
        
        if profesores:
            for profesor in profesores:
                with st.expander(f"{profesor[2]} (Usuario: {profesor[1]})"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Registrado el:** {profesor[3]}")
                        
                        # Obtener clases del profesor
                        conn = get_db_connection()
                        clases = conn.execute(
                            "SELECT id, nombre FROM clases WHERE profesor_id = ?",
                            (profesor[0],)
                        ).fetchall()
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
                                # Verificar si tiene clases asignadas
                                conn = get_db_connection()
                                tiene_clases = conn.execute(
                                    "SELECT 1 FROM clases WHERE profesor_id = ?",
                                    (profesor[0],)
                                ).fetchone()
                                
                                if not tiene_clases:
                                    conn.execute(
                                        "DELETE FROM usuarios WHERE id = ?",
                                        (profesor[0],)
                                    )
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
        
        # Registrar nuevo alumno
        with st.expander("Registrar Nuevo Alumno", expanded=False):
            with st.form("nuevo_alumno"):
                username = st.text_input("Usuario (único)")
                nombre = st.text_input("Nombre completo")
                password = st.text_input("Contraseña", type="password")
                
                if st.form_submit_button("Registrar Alumno"):
                    conn = get_db_connection()
                    try:
                        conn.execute(
                            "INSERT INTO usuarios (username, password, nombre, tipo) VALUES (?, ?, ?, ?)",
                            (username, password, nombre, 'alumno')
                        )
                        conn.commit()
                        st.success("Alumno registrado exitosamente!")
                    except sqlite3.IntegrityError:
                        st.error("El nombre de usuario ya existe")
                    finally:
                        conn.close()
        
        # Inscribir alumno a clase
        with st.expander("Inscribir Alumno a Clase", expanded=False):
            with st.form("inscribir_alumno"):
                conn = get_db_connection()
                alumnos = conn.execute(
                    "SELECT id, nombre FROM usuarios WHERE tipo = 'alumno' ORDER BY nombre"
                ).fetchall()
                
                clases = conn.execute(
                    "SELECT id, nombre FROM clases ORDER BY nombre"
                ).fetchall()
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
                            conn.execute(
                                "INSERT INTO alumnos_clases (alumno_id, clase_id) VALUES (?, ?)",
                                (alumno_id, clase_id)
                            )
                            conn.commit()
                            st.success("Alumno inscrito exitosamente!")
                        except sqlite3.IntegrityError:
                            st.error("Este alumno ya está inscrito en esta clase")
                        finally:
                            conn.close()
                else:
                    st.warning("Necesitas tener al menos un alumno y una clase creada")
        
        # Listado y gestión de alumnos
        st.subheader("Listado de Alumnos")
        conn = get_db_connection()
        alumnos = conn.execute(
            "SELECT id, username, nombre, created_at FROM usuarios WHERE tipo = 'alumno' ORDER BY nombre"
        ).fetchall()
        conn.close()
        
        if alumnos:
            for alumno in alumnos:
                with st.expander(f"{alumno[2]} (Usuario: {alumno[1]})"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Registrado el:** {alumno[3]}")
                        
                        # Obtener clases del alumno
                        conn = get_db_connection()
                        clases = conn.execute(
                            """SELECT c.id, c.nombre 
                            FROM alumnos_clases ac 
                            JOIN clases c ON ac.clase_id = c.id 
                            WHERE ac.alumno_id = ?""",
                            (alumno[0],)
                        ).fetchall()
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
                                conn.execute(
                                    "DELETE FROM usuarios WHERE id = ?",
                                    (alumno[0],)
                                )
                                conn.execute(
                                    "DELETE FROM alumnos_clases WHERE alumno_id = ?",
                                    (alumno[0],)
                                )
                                conn.execute(
                                    "DELETE FROM asistencias WHERE estudiante_id = ?",
                                    (alumno[0],)
                                )
                                conn.commit()
                                conn.close()
                                st.success("Alumno eliminado correctamente")
                                st.rerun()
        else:
            st.info("No hay alumnos registrados")

def vista_profesor():
    st.title("Panel del Profesor")
    
    # Mostrar clases del profesor
    conn = get_db_connection()
    clases = conn.execute(
        """SELECT c.id, c.nombre, c.activa, c.created_at 
        FROM clases c 
        WHERE c.profesor_id = ? 
        ORDER BY c.activa DESC, c.created_at DESC""",
        (st.session_state.user['id'],)
    ).fetchall()
    conn.close()
    
    if clases:
        for clase in clases:
            with st.expander(f"{clase[1]} {'(Activa)' if clase[2] else '(Inactiva)'}"):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    # Obtener token QR
                    conn = get_db_connection()
                    qr_token = conn.execute(
                        "SELECT qr_token FROM clases WHERE id = ?",
                        (clase[0],)
                    ).fetchone()[0]
                    conn.close()
                    
                    url = generar_url_qr(clase[0], qr_token)
                    qr_img = generar_qr(url)
                    img_bytes = img_to_bytes(qr_img)
                    
                    st.image(img_bytes, caption=f"QR para {clase[1]}", width=250)
                    st.code(url, language="text")
                    
                    # Estadísticas
                    conn = get_db_connection()
                    num_alumnos = conn.execute(
                        "SELECT COUNT(*) FROM alumnos_clases WHERE clase_id = ?",
                        (clase[0],)
                    ).fetchone()[0]
                    num_asistencias = conn.execute(
                        "SELECT COUNT(*) FROM asistencias WHERE clase_id = ?",
                        (clase[0],)
                    ).fetchone()[0]
                    conn.close()
                    
                    st.write(f"Alumnos inscritos: {num_alumnos}")
                    st.write(f"Asistencias registradas: {num_asistencias}")
                
                with col2:
                    # Opciones de gestión
                    with st.form(f"opciones_clase_{clase[0]}"):
                        nueva_activa = not clase[2]
                        if st.form_submit_button("Activar" if nueva_activa else "Desactivar"):
                            conn = get_db_connection()
                            conn.execute(
                                "UPDATE clases SET activa = ? WHERE id = ?",
                                (nueva_activa, clase[0])
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()
    else:
        st.info("No tienes clases asignadas")

def vista_alumno():
    st.title("Panel del Alumno")
    st.write(f"Bienvenido/a {st.session_state.user['nombre']}")
    
    # Mostrar clases del alumno
    conn = get_db_connection()
    clases = conn.execute(
        """SELECT c.id, c.nombre, u.nombre as profesor 
        FROM alumnos_clases ac 
        JOIN clases c ON ac.clase_id = c.id 
        JOIN usuarios u ON c.profesor_id = u.id 
        WHERE ac.alumno_id = ?""",
        (st.session_state.user['id'],)
    ).fetchall()
    conn.close()
    
    if clases:
        st.subheader("Tus Clases")
        for clase in clases:
            with st.expander(f"{clase[1]} - Profesor: {clase[2]}"):
                # Mostrar asistencias
                conn = get_db_connection()
                asistencias = conn.execute(
                    "SELECT fecha FROM asistencias WHERE estudiante_id = ? AND clase_id = ? ORDER BY fecha DESC",
                    (st.session_state.user['id'], clase[0])
                ).fetchall()
                conn.close()
                
                if asistencias:
                    st.write("**Tus asistencias:**")
                    for asistencia in asistencias:
                        st.write(f"- {asistencia[0]}")
                else:
                    st.info("No has registrado asistencias en esta clase")
    else:
        st.info("No estás inscrito en ninguna clase")

# Página de registro de asistencia
def registrar_asistencia():
    st.title("Registro de Asistencia")
    
    # Obtener parámetros de la URL
    params = st.query_params
    clase_id = params.get("clase_id", [None])[0]
    token = params.get("token", [None])[0]
    
    if clase_id and token:
        conn = get_db_connection()
        clase = conn.execute(
            "SELECT c.id, c.nombre, u.nombre FROM clases c JOIN usuarios u ON c.profesor_id = u.id WHERE c.id = ? AND c.qr_token = ?",
            (clase_id, token)
        ).fetchone()
        conn.close()
        
        if clase:
            st.success(f"Clase: {clase[1]} con el profesor {clase[2]}")
            
            if 'user' in st.session_state and st.session_state.user['tipo'] == 'alumno':
                # Verificar si ya está registrado
                conn = get_db_connection()
                ya_registrado = conn.execute(
                    "SELECT 1 FROM asistencias WHERE estudiante_id = ? AND clase_id = ?",
                    (st.session_state.user['id'], clase[0])
                ).fetchone()
                
                if not ya_registrado:
                    if st.button("Registrar mi asistencia"):
                        conn.execute(
                            "INSERT INTO asistencias (estudiante_id, clase_id) VALUES (?, ?)",
                            (st.session_state.user['id'], clase[0])
                        )
                        conn.commit()
                        st.success("Asistencia registrada exitosamente!")
                        time.sleep(2)
                        st.rerun()
                else:
                    st.warning("Ya has registrado tu asistencia para esta clase")
                conn.close()
            else:
                st.warning("Debes iniciar sesión como alumno para registrar asistencia")
        else:
            st.error("Enlace de asistencia no válido")
    else:
        st.error("Faltan parámetros en la URL")

# Página principal
def main():
    # Verificar si estamos en la página de registro
    if "clase_id" in st.query_params:
        registrar_asistencia()
        return
    
    if 'user' not in st.session_state:
        login()
    else:
        st.sidebar.title(f"Bienvenido, {st.session_state.user['nombre']}")
        st.sidebar.button("Cerrar Sesión", on_click=logout)
        
        if st.session_state.user['tipo'] == 'admin':
            vista_admin()
        elif st.session_state.user['tipo'] == 'profesor':
            vista_profesor()
        elif st.session_state.user['tipo'] == 'alumno':
            vista_alumno()

if __name__ == "__main__":
    main()