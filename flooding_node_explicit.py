import json
import socket
import threading
import time
import sys

# ---------- Parámetros Generales ----------
PUERTO_BASE = 5000           # Puerto inicial al que se sumará un valor por nodo (por ejemplo A=5000, B=5001...)
TAMANIO_BUFFER = 4096        # Tamaño máximo de datos a recibir por conexión
TIEMPO_ESPERA_INICIAL = 3    # Tiempo para esperar a que todos los nodos inicien
VALOR_TTL_INICIAL = 5        # TTL inicial para los paquetes enviados

# ---------- Funciones auxiliares ----------

def obtener_puerto_desde_nombre(nombre_nodo):
    codigo_ascii = ord(nombre_nodo.upper())
    desplazamiento = codigo_ascii - ord('A')
    puerto = PUERTO_BASE + desplazamiento
    return puerto

def cargar_topologia(nombre_archivo_json, nombre_nodo):
    with open(nombre_archivo_json, 'r') as archivo_json:
        datos_topologia = json.load(archivo_json)
        diccionario_configuracion = datos_topologia["config"]
        vecinos_del_nodo = diccionario_configuracion.get(nombre_nodo, [])
        return vecinos_del_nodo

def enviar_paquete_a_vecino(vecino, mensaje_serializado):
    try:
        puerto_vecino = obtener_puerto_desde_nombre(vecino)
        socket_cliente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_cliente.connect(("localhost", puerto_vecino))
        socket_cliente.sendall(mensaje_serializado.encode())
        socket_cliente.close()
        print("[ENVÍO] Enviado a " + vecino)
    except Exception as error:
        print("[ERROR] No se pudo enviar a " + vecino + ": " + str(error))

# ---------- Componentes del nodo ----------

def escuchar_conexiones(nombre_nodo, lista_vecinos, conjunto_mensajes_recibidos):
    puerto_local = obtener_puerto_desde_nombre(nombre_nodo)
    socket_servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_servidor.bind(("localhost", puerto_local))
    socket_servidor.listen()

    print("[" + nombre_nodo + "] Nodo escuchando en puerto: " + str(puerto_local))

    while True:
        conexion, direccion = socket_servidor.accept()
        datos_recibidos = conexion.recv(TAMANIO_BUFFER).decode()
        conexion.close()

        if datos_recibidos:
            paquete = json.loads(datos_recibidos)

            identificador_mensaje = paquete.get("headers", {}).get("id", None)

            if identificador_mensaje is not None and identificador_mensaje in conjunto_mensajes_recibidos:
                print("[" + nombre_nodo + "] Mensaje duplicado ignorado. ID: " + identificador_mensaje)
                continue

            if identificador_mensaje is not None:
                conjunto_mensajes_recibidos.add(identificador_mensaje)

            destino_paquete = paquete.get("to", "")
            contenido_paquete = paquete.get("payload", "")
            tiempo_vida_restante = paquete.get("ttl", 0)

            if destino_paquete == nombre_nodo:
                print("[" + nombre_nodo + "] Mensaje recibido correctamente: " + contenido_paquete)
            elif tiempo_vida_restante > 0:
                paquete["ttl"] = tiempo_vida_restante - 1
                mensaje_serializado = json.dumps(paquete)
                reenviar_a_vecinos(nombre_nodo, lista_vecinos, mensaje_serializado)

def reenviar_a_vecinos(nombre_nodo, lista_vecinos, mensaje_serializado):
    print("[" + nombre_nodo + "] Reenviando a vecinos...")
    for nombre_vecino in lista_vecinos:
        enviar_paquete_a_vecino(nombre_vecino, mensaje_serializado)

def iniciar_nodo(nombre_nodo, archivo_topologia):
    vecinos_nodo = cargar_topologia(archivo_topologia, nombre_nodo)
    historial_mensajes = set()

    hilo_de_escucha = threading.Thread(
        target=escuchar_conexiones,
        args=(nombre_nodo, vecinos_nodo, historial_mensajes),
        daemon=True
    )
    hilo_de_escucha.start()

    time.sleep(TIEMPO_ESPERA_INICIAL)

    if nombre_nodo.upper() == "A":
        mensaje_inicial = {
            "proto": "flooding",
            "type": "message",
            "from": "A",
            "to": "D",
            "ttl": VALOR_TTL_INICIAL,
            "headers": {
                "id": "msg001"
            },
            "payload": "Saludos desde el nodo A usando Flooding."
        }
        mensaje_serializado = json.dumps(mensaje_inicial)
        reenviar_a_vecinos(nombre_nodo, vecinos_nodo, mensaje_serializado)

    while True:
        time.sleep(1)  # Mantener el hilo principal vivo

# ---------- Punto de entrada principal ----------


if len(sys.argv) != 3:
    print("Uso correcto: python flooding_node_explicit.py <NOMBRE_NODO> <ARCHIVO_TOPOLOGIA>")
    sys.exit(1)

nombre_nodo_ingresado = sys.argv[1]
archivo_topologia_ingresado = sys.argv[2]

iniciar_nodo(nombre_nodo_ingresado, archivo_topologia_ingresado)
