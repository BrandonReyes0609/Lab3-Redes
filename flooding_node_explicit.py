import json
import socket
import threading
import time
import sys
import uuid
from datetime import datetime


PUERTO_BASE = 5000
TAMANIO_BUFFER = 4096
TIEMPO_ESPERA_INICIAL = 3
VALOR_TTL_INICIAL = 5
TIMEOUT_SOCKET = 2.0

class FloodingNode:
    def __init__(self, nombre_nodo, archivo_topologia):
        self.nombre_nodo = nombre_nodo.upper()
        self.vecinos = self.cargar_topologia(archivo_topologia)
        self.mensajes_recibidos = set()  
        self.puerto = self.obtener_puerto()
        self.socket_servidor = None
        self.activo = True
        
        print(f"[{self.nombre_nodo}] Nodo inicializado con vecinos: {self.vecinos}")
    
    def obtener_puerto(self):
        codigo_ascii = ord(self.nombre_nodo)
        desplazamiento = codigo_ascii - ord('A')
        return PUERTO_BASE + desplazamiento
    
    def cargar_topologia(self, archivo_json):
        try:
            with open(archivo_json, 'r', encoding='utf-8') as archivo:
                datos_topologia = json.load(archivo)
                vecinos = datos_topologia["config"].get(self.nombre_nodo, [])
                return vecinos
        except Exception as e:
            print(f"[ERROR] No se pudo cargar topología: {e}")
            return []
    
    def crear_mensaje(self, destino, contenido, tipo="message"):
        return {
            "proto": "flooding",
            "type": tipo,
            "from": self.nombre_nodo,
            "to": destino,
            "ttl": VALOR_TTL_INICIAL,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat()
            },
            "payload": contenido
        }
    
    def enviar_a_vecino(self, vecino, mensaje_json):
        try:
            puerto_vecino = PUERTO_BASE + (ord(vecino) - ord('A'))
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(TIMEOUT_SOCKET)
                sock.connect(("localhost", puerto_vecino))
                sock.sendall(mensaje_json.encode('utf-8'))
                
            print(f"[{self.nombre_nodo}] Enviado a {vecino}")
            return True
            
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error enviando a {vecino}: {e}")
            return False
    
    def flooding_broadcast(self, mensaje):
        mensaje_json = json.dumps(mensaje, ensure_ascii=False)
        
        print(f"[{self.nombre_nodo}] Aplicando flooding a vecinos: {self.vecinos}")
        
        enviados_exitosos = 0
        for vecino in self.vecinos:
            if self.enviar_a_vecino(vecino, mensaje_json):
                enviados_exitosos += 1
        
        print(f"[{self.nombre_nodo}] Flooding completado: {enviados_exitosos}/{len(self.vecinos)} enviados")
    
    def procesar_mensaje_recibido(self, mensaje):
        try:
            paquete = json.loads(mensaje)
            
            
            msg_id = paquete.get("headers", {}).get("id")
            destino = paquete.get("to", "")
            contenido = paquete.get("payload", "")
            ttl = paquete.get("ttl", 0)
            origen = paquete.get("from", "")
            
            
            if msg_id and msg_id in self.mensajes_recibidos:
                print(f"[{self.nombre_nodo}] Mensaje duplicado ignorado (ID: {msg_id})")
                return
            
            
            if msg_id:
                self.mensajes_recibidos.add(msg_id)
            
            print(f"[{self.nombre_nodo}] Mensaje recibido de {origen} -> {destino} (TTL: {ttl})")
            
            
            if destino == self.nombre_nodo:
                print(f"[{self.nombre_nodo}] MENSAJE DESTINO: '{contenido}'")
                
                return
            
            
            if ttl > 0:
                paquete["ttl"] = ttl - 1
                print(f"[{self.nombre_nodo}] Reenviando mensaje (nuevo TTL: {ttl-1})")
                self.flooding_broadcast(paquete)
            else:
                print(f"[{self.nombre_nodo}] Mensaje descartado (TTL agotado)")
                
        except json.JSONDecodeError as e:
            print(f"[{self.nombre_nodo}] Error decodificando JSON: {e}")
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error procesando mensaje: {e}")
    
    def escuchar_conexiones(self):
        try:
            self.socket_servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket_servidor.bind(("localhost", self.puerto))
            self.socket_servidor.listen(5)
            
            print(f"[{self.nombre_nodo}] Escuchando en puerto {self.puerto}")
            
            while self.activo:
                try:
                    conexion, direccion = self.socket_servidor.accept()
                    
                    
                    hilo_conexion = threading.Thread(
                        target=self.manejar_conexion,
                        args=(conexion,),
                        daemon=True
                    )
                    hilo_conexion.start()
                    
                except socket.error as e:
                    if self.activo:  
                        print(f"[{self.nombre_nodo}] Error en socket: {e}")
                        
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error en servidor: {e}")
        finally:
            if self.socket_servidor:
                self.socket_servidor.close()
    
    def manejar_conexion(self, conexion):
        try:
            with conexion:
                datos = conexion.recv(TAMANIO_BUFFER).decode('utf-8')
                if datos:
                    self.procesar_mensaje_recibido(datos)
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error manejando conexión: {e}")
    
    def enviar_mensaje_inicial(self):
        if self.nombre_nodo == "A":
            time.sleep(TIEMPO_ESPERA_INICIAL)  
            
            mensaje = self.crear_mensaje(
                destino="D",
                contenido=f"¡Saludos desde el nodo {self.nombre_nodo} usando Flooding! - {datetime.now().strftime('%H:%M:%S')}"
            )
            
            print(f"[{self.nombre_nodo}] Iniciando comunicación...")
            self.flooding_broadcast(mensaje)
    
    def iniciar(self):
        print(f"[{self.nombre_nodo}] Iniciando nodo flooding...")
        
        
        hilo_servidor = threading.Thread(target=self.escuchar_conexiones, daemon=True)
        hilo_servidor.start()
        
        
        hilo_inicial = threading.Thread(target=self.enviar_mensaje_inicial, daemon=True)
        hilo_inicial.start()
        
        try:
            while self.activo:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print(f"\n[{self.nombre_nodo}] Deteniendo nodo...")
            self.activo = False
            if self.socket_servidor:
                self.socket_servidor.close()

def main():
    if len(sys.argv) != 3:
        sys.exit(1)
    
    nombre_nodo = sys.argv[1].upper()
    archivo_topologia = sys.argv[2]
    
    nodo = FloodingNode(nombre_nodo, archivo_topologia)
    nodo.iniciar()

if __name__ == "__main__":
    main()