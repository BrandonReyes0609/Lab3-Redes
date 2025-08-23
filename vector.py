import json
import socket
import threading
import time
import sys
import uuid
from datetime import datetime
from collections import defaultdict


PUERTO_BASE = 5000
TAMANIO_BUFFER = 4096
TIEMPO_ESPERA_INICIAL = 3
TIMEOUT_SOCKET = 2.0
INTERVALO_ACTUALIZACION = 10  
MAX_DISTANCIA = 16  

class DistanceVectorNode:
    def __init__(self, nombre_nodo, archivo_topologia):
        self.nombre_nodo = nombre_nodo.upper()
        self.puerto = PUERTO_BASE + (ord(self.nombre_nodo) - ord('A'))
        self.vecinos = self.cargar_vecinos(archivo_topologia)
        self.activo = True
        self.socket_servidor = None
        self.mensajes_procesados = set()
        
        
        self.tabla_enrutamiento = {}
        
        
        self.tablas_vecinos = defaultdict(dict)
        
        
        self.inicializar_tabla()
        
        print(f"[{self.nombre_nodo}] Nodo DVR inicializado con vecinos: {self.vecinos}")
        self.mostrar_tabla_enrutamiento()
    
    def cargar_vecinos(self, archivo_json):
        try:
            with open(archivo_json, 'r', encoding='utf-8') as archivo:
                datos_topologia = json.load(archivo)
                vecinos = datos_topologia["config"].get(self.nombre_nodo, [])
                return vecinos
        except Exception as e:
            print(f"[ERROR] No se pudo cargar topología: {e}")
            return []
    
    def inicializar_tabla(self):
        
        self.tabla_enrutamiento[self.nombre_nodo] = {
            'distance': 0,
            'next_hop': self.nombre_nodo
        }
        
        
        for vecino in self.vecinos:
            self.tabla_enrutamiento[vecino] = {
                'distance': 1,
                'next_hop': vecino
            }
        
        print(f"[{self.nombre_nodo}] Tabla inicial creada")
    
    def crear_mensaje_vector(self):
        vector_distancias = {}
        for destino, info in self.tabla_enrutamiento.items():
            
            vector_distancias[destino] = info['distance']
        
        return {
            "proto": "dvr",
            "type": "distance_vector",
            "from": self.nombre_nodo,
            "to": "broadcast",  
            "ttl": 1,  
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "algorithm": "distance_vector"
            },
            "payload": vector_distancias
        }
    
    def crear_mensaje_datos(self, destino, contenido):
        return {
            "proto": "dvr",
            "type": "message",
            "from": self.nombre_nodo,
            "to": destino,
            "ttl": 15,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat()
            },
            "payload": contenido
        }
    
    def actualizar_tabla_con_vector_vecino(self, vecino, vector_distancias):
        self.tablas_vecinos[vecino] = vector_distancias
        tabla_actualizada = False
        
        print(f"[{self.nombre_nodo}] Procesando vector de {vecino}")
        
        
        for destino, distancia_vecino in vector_distancias.items():
            if destino == self.nombre_nodo:
                continue  
            
            
            distancia_via_vecino = 1 + distancia_vecino  
            
            
            if (destino not in self.tabla_enrutamiento or 
                distancia_via_vecino < self.tabla_enrutamiento[destino]['distance']):
                
                self.tabla_enrutamiento[destino] = {
                    'distance': distancia_via_vecino,
                    'next_hop': vecino
                }
                tabla_actualizada = True
                print(f"[{self.nombre_nodo}] Ruta mejorada a {destino}: {distancia_via_vecino} via {vecino}")
        
        
        rutas_a_eliminar = []
        for destino, info in self.tabla_enrutamiento.items():
            if info['next_hop'] == vecino and destino not in vector_distancias:
                
                rutas_a_eliminar.append(destino)
        
        for destino in rutas_a_eliminar:
            self.tabla_enrutamiento[destino]['distance'] = MAX_DISTANCIA
            tabla_actualizada = True
            print(f"[{self.nombre_nodo}] Ruta a {destino} inalcanzable")
        
        if tabla_actualizada:
            self.mostrar_tabla_enrutamiento()
            
            self.enviar_vector_a_vecinos()
    
    def enviar_vector_a_vecinos(self):
        mensaje = self.crear_mensaje_vector()
        
        for vecino in self.vecinos:
            self.enviar_a_vecino(vecino, mensaje)
    
    def enviar_a_vecino(self, vecino, mensaje):
        try:
            puerto_vecino = PUERTO_BASE + (ord(vecino) - ord('A'))
            mensaje_json = json.dumps(mensaje, ensure_ascii=False)
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(TIMEOUT_SOCKET)
                sock.connect(("localhost", puerto_vecino))
                sock.sendall(mensaje_json.encode('utf-8'))
            
            if mensaje['type'] == 'distance_vector':
                print(f"[{self.nombre_nodo}] Vector enviado a {vecino}")
            else:
                print(f"[{self.nombre_nodo}] Mensaje enviado a {vecino}")
            return True
            
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error enviando a {vecino}: {e}")
            return False
    
    def reenviar_mensaje(self, destino, paquete):
        if destino not in self.tabla_enrutamiento:
            print(f"[{self.nombre_nodo}] No hay ruta conocida a {destino}")
            return False
        
        info_ruta = self.tabla_enrutamiento[destino]
        if info_ruta['distance'] >= MAX_DISTANCIA:
            print(f"[{self.nombre_nodo}] Destino {destino} inalcanzable")
            return False
        
        siguiente_salto = info_ruta['next_hop']
        print(f"[{self.nombre_nodo}] Reenviando a {destino} via {siguiente_salto} (dist: {info_ruta['distance']})")
        
        return self.enviar_a_vecino(siguiente_salto, paquete)
    
    def procesar_mensaje_recibido(self, mensaje):
        try:
            paquete = json.loads(mensaje)
            
            tipo_mensaje = paquete.get("type", "")
            origen = paquete.get("from", "")
            destino = paquete.get("to", "")
            contenido = paquete.get("payload", "")
            msg_id = paquete.get("headers", {}).get("id")
            ttl = paquete.get("ttl", 0)
            
            
            if msg_id and msg_id in self.mensajes_procesados:
                return
            
            if msg_id:
                self.mensajes_procesados.add(msg_id)
            
            if tipo_mensaje == "distance_vector":
                
                print(f"[{self.nombre_nodo}] Vector recibido de {origen}")
                self.actualizar_tabla_con_vector_vecino(origen, contenido)
                
            elif tipo_mensaje == "message":
                print(f"[{self.nombre_nodo}] Mensaje de {origen} para {destino}")
                
                if destino == self.nombre_nodo:
                    print(f"[{self.nombre_nodo}] MENSAJE RECIBIDO: '{contenido}'")
                elif ttl > 0:
                    paquete["ttl"] = ttl - 1
                    self.reenviar_mensaje(destino, paquete)
                else:
                    print(f"[{self.nombre_nodo}] TTL agotado")
            
            elif tipo_mensaje == "hello":
                
                print(f"[{self.nombre_nodo}] Hello recibido de {origen}")
                
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error procesando mensaje: {e}")
    
    def mostrar_tabla_enrutamiento(self):
        print(f"\n[{self.nombre_nodo}] TABLA DE ENRUTAMIENTO DVR:")
        print("-" * 45)
        print("Destino | Distancia | Siguiente Salto")
        print("-" * 45)
        
        for destino, info in sorted(self.tabla_enrutamiento.items()):
            distancia = info['distance']
            siguiente = info['next_hop']
            distancia_str = str(distancia) if distancia < MAX_DISTANCIA else "∞"
            
            print(f"{destino:^7} | {distancia_str:^9} | {siguiente:^14}")
        
        print("-" * 45)
    
    def actualizacion_periodica(self):
        while self.activo:
            time.sleep(INTERVALO_ACTUALIZACION)
            if self.activo:
                print(f"[{self.nombre_nodo}] Enviando actualización periódica")
                self.enviar_vector_a_vecinos()
    
    def escuchar_conexiones(self):
        try:
            self.socket_servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket_servidor.bind(("localhost", self.puerto))
            self.socket_servidor.listen(5)
            
            print(f"[{self.nombre_nodo}] Escuchando en puerto {self.puerto}")
            
            while self.activo:
                try:
                    conexion, _ = self.socket_servidor.accept()
                    
                    hilo_conexion = threading.Thread(
                        target=self.manejar_conexion,
                        args=(conexion,),
                        daemon=True
                    )
                    hilo_conexion.start()
                    
                except socket.error as e:
                    if self.activo:
                        print(f"[{self.nombre_nodo}] Error socket: {e}")
                        
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error servidor: {e}")
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
            print(f"[{self.nombre_nodo}] Error en conexión: {e}")
    
    def enviar_mensaje_inicial(self):
        time.sleep(TIEMPO_ESPERA_INICIAL)
        
        
        print(f"[{self.nombre_nodo}] Enviando vector inicial...")
        self.enviar_vector_a_vecinos()
        
        
        if self.nombre_nodo == "A":
            time.sleep(5)  
            
            mensaje = self.crear_mensaje_datos(
                destino="D",
                contenido=f"¡Mensaje desde {self.nombre_nodo} usando DVR! - {datetime.now().strftime('%H:%M:%S')}"
            )
            
            print(f"[{self.nombre_nodo}] Enviando mensaje de prueba...")
            if "D" in self.tabla_enrutamiento and self.tabla_enrutamiento["D"]["distance"] < MAX_DISTANCIA:
                self.reenviar_mensaje("D", mensaje)
            else:
                print(f"[{self.nombre_nodo}] No hay ruta a D disponible aún")
    
    def iniciar(self):
        print(f"[{self.nombre_nodo}] Iniciando nodo Distance Vector")
        
        
        hilo_servidor = threading.Thread(target=self.escuchar_conexiones, daemon=True)
        hilo_servidor.start()
        
        
        hilo_actualizacion = threading.Thread(target=self.actualizacion_periodica, daemon=True)
        hilo_actualizacion.start()
        
        
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
    
    
    nodo = DistanceVectorNode(nombre_nodo, archivo_topologia)
    nodo.iniciar()

if __name__ == "__main__":
    main()