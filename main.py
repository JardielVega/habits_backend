import os
from pathlib import Path
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from groq import Groq

# 1. Leer las llaves del archivo .env automáticamente
load_dotenv()

# Inicializar FastAPI (nuestro servidor backend)
app = FastAPI()


# Configuración de CORS: Esto permite que tu HTML/JS local pueda hablar con este Backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Conectar los clientes de Supabase y Groq (IA) usando tus llaves
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")
groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

supabase: Optional[Client] = None
groq_client = None

if supabase_url and supabase_key:
    supabase = create_client(supabase_url, supabase_key)

if groq_api_key:
    groq_client = Groq(api_key=groq_api_key)

BASE_DIR = Path(__file__).resolve().parent
CONOCIMIENTO_PATH = BASE_DIR / "conocimiento.txt"


# 3. MOLDES DE DATOS (Pydantic): Definen qué estructura de datos nos enviará tu JavaScript
class LoginRegistroData(BaseModel):
    email: str
    password: str

class NuevoHabitoData(BaseModel):
    usuario_id: str
    nombre_habito: str
    frecuencia: str

class CheckHabitoData(BaseModel):
    habito_id: int
    completado: bool
    nota_emocional: str = ""


# 4. RUTAS PARA LOGIN Y REGISTRO (Conectado a Supabase Auth)

@app.post("/auth/registro")
def registrar_usuario(data: LoginRegistroData):
    try:
        respuesta = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
        })
        return {"status": "success", "message": "Usuario registrado con éxito", "user": respuesta.user}
    except Exception as e:
        print(f"Error en registro: {e}")
        raise HTTPException(status_code=400, detail=f"No se pudo registrar: {str(e)}")

@app.post("/auth/login")
def login_usuario(data: LoginRegistroData):
    try:
        respuesta = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password,
        })
        return {
            "status": "success",
            "message": "Sesión iniciada",
            "user": {
                "email": respuesta.user.email,
                "id": respuesta.user.id,
            },
        }
    except Exception as e:
        print(f"Error en login: {e}")
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")


# 5. RUTAS PARA GESTIONAR HÁBITOS (Conectado a tus tablas de Supabase)

@app.post("/habitos")
def agregar_habito(datos: NuevoHabitoData):
    """Guarda un nuevo hábito en la base de datos"""
    try:
        respuesta = supabase.table("habitos").insert({
            "usuario_id": datos.usuario_id,
            "nombre_habito": datos.nombre_habito,
            "frecuencia": datos.frecuencia
        }).execute()
        return {"status": "success", "data": respuesta.data[0]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/habitos")
def obtener_habitos(usuario_id: str):
    """Trae todos los hábitos que le pertenecen a un usuario específico"""
    try:
        data = supabase.table("habitos").select("*").eq("usuario_id", usuario_id).execute()
        return data.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/habitos/{usuario_id}")
def obtener_habitos_por_id(usuario_id: str):
    """Trae todos los hábitos que le pertenecen a un usuario específico"""
    try:
        data = supabase.table("habitos").select("*").eq("usuario_id", usuario_id).execute()
        return data.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/habitos/{habito_id}")
def eliminar_habito(habito_id: int):
    """Elimina un hábito de la base de datos usando su ID"""
    try:
        supabase.table("habitos").delete().eq("id", habito_id).execute()
        return {"mensaje": "Hábito eliminado con éxito"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/habitos/check")
def cumplir_habito(datos: CheckHabitoData):
    """Registra en la base de datos cuándo se marca un hábito como hecho"""
    try:
        fecha_actual = datetime.utcnow()
        fecha_actual_iso = fecha_actual.isoformat()
        fecha_actual_dia = fecha_actual.date()

        data = supabase.table("registro_habitos").insert({
            "habito_id": datos.habito_id,
            "fecha": fecha_actual_iso,
            "completado": datos.completado,
            "nota_emocional": datos.nota_emocional
        }).execute()

        if supabase is not None:
            habito_actual = supabase.table("habitos")\
                .select("id, racha, ultimo_completado, completado_hoy")\
                .eq("id", datos.habito_id)\
                .limit(1).execute()

            if habito_actual.data:
                registro = habito_actual.data[0]
                ultimo_completado = registro.get("ultimo_completado")
                racha_actual = registro.get("racha") or 0
                ultimo_dia = None

                if ultimo_completado:
                    try:
                        ultimo_dia = datetime.fromisoformat(str(ultimo_completado).replace("Z", "+00:00")).date()
                    except ValueError:
                        ultimo_dia = None

                if datos.completado:
                    if ultimo_dia == fecha_actual_dia:
                        nueva_racha = racha_actual
                    else:
                        nueva_racha = racha_actual + 1

                    supabase.table("habitos").update({
                        "completado_hoy": True,
                        "ultimo_completado": fecha_actual_iso,
                        "racha": nueva_racha,
                    }).eq("id", datos.habito_id).execute()
                else:
                    nueva_racha = racha_actual - 1 if ultimo_dia == fecha_actual_dia and racha_actual > 0 else racha_actual

                    supabase.table("habitos").update({
                        "completado_hoy": False,
                        "racha": nueva_racha,
                    }).eq("id", datos.habito_id).execute()

        return data.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# 6. LA RUTA DEL AGENTE DE IA (RAG AUTOMÁTICO)

@app.get("/agente/consejo")
def obtener_consejo_ia(habito_id: int, nombre_habito: str, pregunta: str):
    """Lee tus apuntes locales, mira el historial del usuario y consulta a Groq"""
    try:
        # A. Leer tu archivo de apuntes especializado
        try:
            teoria_experta = CONOCIMIENTO_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            teoria_experta = "No se encontró conocimiento local adicional."

        # B. Buscar en Supabase qué ha hecho el usuario con este hábito en los últimos 7 días
        historial_texto = "[]"
        if supabase is not None:
            historial_bd = supabase.table("registro_habitos")\
                .select("fecha, completado, nota_emocional")\
                .eq("habito_id", habito_id)\
                .order("fecha", desc=True)\
                .limit(7).execute()
            historial_texto = str(historial_bd.data)

        # C. Construir las instrucciones secretas para el modelo Llama 3
        prompt_sistema = f"""
        Eres un Agente Coach experto en psicología conductual y formación de hábitos. 
        Tu objetivo es guiar al usuario usando conceptos de tus libros de interés.
        
        TU BASE DE CONOCIMIENTO (Usa estas reglas para tus respuestas):
        {teoria_experta}
        
        HISTORIAL DE RENDIMIENTO REAL DEL USUARIO (Últimos 7 días para el hábito '{nombre_habito}'):
        {historial_texto}
        
        Responde de forma clara, motivadora y en español. Evita respuestas excesivamente largas.
        """

        # D. Hacer la consulta gratuita a Groq con un modelo vigente
        if groq_client is not None:
            conversion = groq_client.chat.completions.create(
                model=groq_model,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": pregunta}
                ],
                temperature=0.7
            )

            return {"consejo": conversion.choices[0].message.content}

        consejo_respaldo = (
            f"Sobre '{nombre_habito}', empieza con una versión más pequeña de lo que intentas hacer. "
            f"Si hoy te cuesta, reduce la fricción: prepara el entorno, fija una hora concreta y haz solo el primer paso. "
            f"Tu pregunta fue: {pregunta}."
        )
        return {"consejo": consejo_respaldo}
        
    except Exception as e:
        consejo_respaldo = (
            f"No pude consultar la IA ahora mismo. Para '{nombre_habito}', prioriza una acción mínima hoy, "
            f"repite a la misma hora mañana y evita intentar hacerlo perfecto desde el inicio."
        )
        return {"consejo": consejo_respaldo, "detail": str(e)}