# 🧠 Laboratorio 3 - Algoritmos de Enrutamiento
Comunicación entre nodos usando interfaces gráficas (GUI) y protocolos de enrutamiento en Python.  
Permite enviar mensajes directos entre nodos utilizando **Sockets locales** o **Redis (Pub/Sub)**.

---

## 📦 Requisitos

- Python 3.10+ (recomendado)
- pip

---

## ✅ Instalación de dependencias

Instala las librerías necesarias con:

```bash
pip install redis
```

Para generar el archivo de dependencias automáticamente (opcional):

```bash
pip install pipreqs
pipreqs . --force
```

---

## 📁 Estructura esperada del proyecto

```
.
├── gui_sender.py
├── render.py
├── redis_flooding_node.py
├── redis_dvr_node.py
├── redis_lsr_node.py
├── config_node_A.json
├── config_node_B.json
├── ...
└── requirements.txt
```

---

## 🚀 Ejecución en modo WebSocket (sockets locales)

Abre una terminal por nodo y ejecuta:

```bash
python gui_sender.py A config_node_A.json
python gui_sender.py B config_node_A.json
python gui_sender.py C config_node_A.json
python gui_sender.py D config_node_A.json
```

🟢 Cada GUI mostrará el nodo y sus vecinos cargados desde el archivo `config_node_A.json`.

---

## ☁️ Ejecución en modo Redis

Usa el archivo `render.py` (GUI avanzada) y asegúrate que el archivo `.json` contenga la sección de Redis:

```json
"redis": {
  "host": "lab3.redesuvg.cloud",
  "port": 6379,
  "password": "UVGRedis2025"
}
```

### 1. Ejecuta `render.py`

```bash
python render.py
```

### 2. En la interfaz:
- Haz clic en **"Cargar Config JSON"**
- Selecciona el archivo `config_node_X.json`
- Haz clic en **"Conectar"**

📡 El nodo se conecta a Redis y se comunica mediante canales Pub/Sub.

---

## 📤 Formato de archivos `config_node_X.json`

```json
{
  "node_id": "A",
  "topology": {
    "A": ["B", "C"],
    "B": ["A", "D"],
    "C": ["A", "D"],
    "D": ["B", "C"]
  },
  "redis": {
    "host": "lab3.redesuvg.cloud",
    "port": 6379,
    "password": "UVGRedis2025"
  },
  "channels": {
    "subscribe": ["sec20.topologia1.nodea"],
    "neighbors": {
      "B": "sec20.topologia1.nodeb",
      "C": "sec20.topologia1.nodec"
    }
  }
}
```

---

## 📌 Comandos disponibles en la GUI

- Enviar mensaje directo a un nodo
- Enviar echo
- Ver vecinos
- Mostrar logs
- Ver topología

---

## 🛠️ Notas

- Redis debe estar accesible en tu red (asegúrate de no estar bloqueado por firewall)
- Puedes usar tu propio servidor Redis si el de UVG no está disponible
- El puerto base para sockets locales es `5000 + índice de nodo (A=0, B=1, etc)`

---

## 👨‍💻 Autor
Universidad del Valle de Guatemala  
Curso: Redes de Computadoras  
Laboratorio 3 - Parte 2