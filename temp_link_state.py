import json
import socket
import threading
import time
import sys
import uuid
import heapq
from datetime import datetime
from collections import defaultdict


PUERTO_BASE = 6000
TAMANIO_BUFFER = 4096
TIEMPO_ESPERA_INICIAL = 10
TIMEOUT_SOCKET = 2.0
INTERVALO_LSP = 30  
TIEMPO_VIDA_LSP = 60  

class LinkStateDatabase:
    
    def __init__(self):
        
        self.lsdb = {}
        self.lock = threading.Lock()
    
    def actualizar_lsp(self, nodo_origen, secuencia, vecinos, timestamp):
        with self.lock:
            if (nodo_origen not in self.lsdb or 
                secuencia > self.lsdb[nodo_origen]['secuencia'] or
                (secuencia == self.lsdb[nodo_origen]['secuencia'] and 
                 timestamp > self.lsdb[nodo_origen]['timestamp'])):
                
                self.lsdb[nodo_origen] = {
                    'secuencia': secuencia,
                    'vecinos': vecinos,
                    'timestamp': timestamp
                }
                return True  
            return False  
    
    def obtener_topologia_completa(self):
        with self.lock:
            topologia = defaultdict(dict)
            
            for nodo, info in self.lsdb.items():
                
                if time.time() - info['timestamp'] > TIEMPO_VIDA_LSP:
                    continue
                    
                for vecino in info['vecinos']:
                    
                    topologia[nodo][vecino] = 1
            
            return dict(topologia)
    
    def obtener_lsp(self, nodo):
        with self.lock:
            return self.lsdb.get(nodo, None)
    
    def listar_todos_lsp(self):
        with self.lock:
            return dict(self.lsdb)

class DijkstraLSR:
    
    @staticmethod
    def calcular_rutas(topologia, nodo_origen):
        if nodo_origen not in topologia:
            return {}
        
        
        distancias = {nodo: float('inf') for nodo in topologia}
        distancias[nodo_origen] = 0
        predecesores = {nodo: None for nodo in topologia}
        visitados = set()
        
        
        cola = [(0, nodo_origen)]
        
        while cola:
            distancia_actual, nodo_actual = heapq.heappop(cola)
            
            if nodo_actual in visitados:
                continue
            
            visitados.add(nodo_actual)
            
            
            for vecino, peso in topologia.get(nodo_actual, {}).items():
                if vecino not in visitados:
                    nueva_distancia = distancia_actual + peso
                    
                    if nueva_distancia < distancias[vecino]:
                        distancias[vecino] = nueva_distancia
                        predecesores[vecino] = nodo_actual
                        heapq.heappush(cola, (nueva_distancia, vecino))
        
        
        tabla_enrutamiento = {}
        
        for destino in topologia:
            if destino != nodo_origen and distancias[destino] != float('inf'):
                
                ruta = []
                nodo_temp = destino
                
                while nodo_temp is not None:
                    ruta.append(nodo_temp)
                    nodo_temp = predecesores[nodo_temp]
                
                ruta.reverse()
                
                if len(ruta) > 1:
                    siguiente_salto = ruta[1]
                    tabla_enrutamiento[destino] = {
                        'next_hop': siguiente_salto,
                        'distance': distancias[destino],
                        'ruta': ruta
                    }
        
        return tabla_enrutamiento

class LinkStateNode:
    def __init__(self, nombre_nodo, archivo_topologia):
        self.nombre_nodo = nombre_nodo.upper()
        self.puerto = PUERTO_BASE + (ord(self.nombre_nodo) - ord('A'))
        self.vecinos = self.cargar_vecinos(archivo_topologia)
        self.activo = True
        self.socket_servidor = None
        self.mensajes_procesados = set()
        
        
        self.lsdb = LinkStateDatabase()
        
        
        self.tabla_enrutamiento = {}
        
        
        self.secuencia_lsp = 0
        
        
        self.generar_lsp_propio()
        
        print(f"[{self.nombre_nodo}] Nodo LSR inicializado con vecinos: {self.vecinos}")
    
    def cargar_vecinos(self, archivo_json):
        try:
            with open(archivo_json, 'r', encoding='utf-8') as archivo:
                datos_topologia = json.load(archivo)
                vecinos = datos_topologia["config"].get(self.nombre_nodo, [])
                return vecinos
        except Exception as e:
            print(f"[ERROR] No se pudo cargar topología: {e}")
            return []
    
    def generar_lsp_propio(self):
        self.secuencia_lsp += 1
        timestamp = time.time()
        
        self.lsdb.actualizar_lsp(
            self.nombre_nodo,
            self.secuencia_lsp,
            self.vecinos,
            timestamp
        )
        
        print(f"[{self.nombre_nodo}] LSP generado (seq: {self.secuencia_lsp})")
    
    def crear_mensaje_lsp(self, nodo_origen, secuencia, vecinos, timestamp):
        return {
            "proto": "lsr",
            "type": "lsp",
            "from": self.nombre_nodo,
            "to": "broadcast",
            "ttl": 15,  
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "lsp_origen": nodo_origen,
                "lsp_secuencia": secuencia,
                "lsp_timestamp": timestamp
            },
            "payload": {
                "nodo_origen": nodo_origen,
                "secuencia": secuencia,
                "vecinos": vecinos,
                "timestamp": timestamp
            }
        }
    
    def crear_mensaje_datos(self, destino, contenido):
        return {
            "proto": "lsr",
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
    
    def flooding_lsp(self, mensaje_lsp):
        mensaje_json = json.dumps(mensaje_lsp, ensure_ascii=False)
        
        enviados = 0
        for vecino in self.vecinos:
            if self.enviar_a_vecino(vecino, mensaje_json):
                enviados += 1
        
        print(f"[{self.nombre_nodo}] LSP enviado por flooding: {enviados}/{len(self.vecinos)}")
    
    def enviar_a_vecino(self, vecino, mensaje_json):
        try:
            puerto_vecino = PUERTO_BASE + (ord(vecino) - ord('A'))
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(TIMEOUT_SOCKET)
                sock.connect(("localhost", puerto_vecino))
                sock.sendall(mensaje_json.encode('utf-8'))
            
            return True
            
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error enviando a {vecino}: {e}")
            return False
    
    def procesar_lsp_recibido(self, paquete):
        payload = paquete.get("payload", {})
        nodo_origen = payload.get("nodo_origen")
        secuencia = payload.get("secuencia")
        vecinos = payload.get("vecinos", [])
        timestamp = payload.get("timestamp")
        
        print(f"[{self.nombre_nodo}] LSP recibido de {nodo_origen} (seq: {secuencia})")
        
        
        lsp_nuevo = self.lsdb.actualizar_lsp(nodo_origen, secuencia, vecinos, timestamp)
        
        if lsp_nuevo:
            print(f"[{self.nombre_nodo}] LSDB actualizada con LSP de {nodo_origen}")
            
            
            self.calcular_tabla_enrutamiento()
            
            
            origen_mensaje = paquete.get("from")
            if origen_mensaje != self.nombre_nodo:  
                self.reenviar_lsp(paquete, origen_mensaje)
        else:
            print(f"[{self.nombre_nodo}] LSP de {nodo_origen} ignorado (más antiguo)")
    
    def reenviar_lsp(self, paquete, origen_mensaje):
        if paquete.get("ttl", 0) <= 0:
            return
        
        paquete["ttl"] = paquete["ttl"] - 1
        paquete["from"] = self.nombre_nodo  
        
        mensaje_json = json.dumps(paquete, ensure_ascii=False)
        
        reenviados = 0
        for vecino in self.vecinos:
            if vecino != origen_mensaje:  
                if self.enviar_a_vecino(vecino, mensaje_json):
                    reenviados += 1
        
        print(f"[{self.nombre_nodo}] LSP reenviado: {reenviados} vecinos")
    
    def calcular_tabla_enrutamiento(self):
        topologia = self.lsdb.obtener_topologia_completa()
        
        if not topologia:
            print(f"[{self.nombre_nodo}] Topología vacía")
            return
        
        self.tabla_enrutamiento = DijkstraLSR.calcular_rutas(topologia, self.nombre_nodo)
        
        print(f"[{self.nombre_nodo}] Tabla de enrutamiento recalculada")
        self.mostrar_tabla_enrutamiento()
    
    def mostrar_tabla_enrutamiento(self):
        print(f"\n[{self.nombre_nodo}] TABLA DE ENRUTAMIENTO LSR:")
        print("-" * 60)
        print("Destino | Siguiente Salto | Distancia | Ruta")
        print("-" * 60)
        
        for destino, info in sorted(self.tabla_enrutamiento.items()):
            ruta_str = " -> ".join(info['ruta'])
            print(f"{destino:^7} | {info['next_hop']:^14} | {info['distance']:^9} | {ruta_str}")
        
        print("-" * 60)
        print(f"Topología conocida: {len(self.lsdb.obtener_topologia_completa())} nodos")
        print()
    
    def reenviar_mensaje_datos(self, destino, paquete):
        if destino not in self.tabla_enrutamiento:
            print(f"[{self.nombre_nodo}] No hay ruta conocida a {destino}")
            return False
        
        info = self.tabla_enrutamiento[destino]
        siguiente_salto = info['next_hop']
        
        mensaje_json = json.dumps(paquete, ensure_ascii=False)
        
        print(f"[{self.nombre_nodo}] Reenviando a {destino} via {siguiente_salto}")
        print(f"[{self.nombre_nodo}] Ruta: {' -> '.join(info['ruta'])}")
        
        return self.enviar_a_vecino(siguiente_salto, mensaje_json)
    
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
            
            if tipo_mensaje == "lsp":
                
                self.procesar_lsp_recibido(paquete)
                
            elif tipo_mensaje == "message":
                print(f"[{self.nombre_nodo}] Mensaje de {origen} para {destino}")
                
                if destino == self.nombre_nodo:
                    print(f"[{self.nombre_nodo}] MENSAJE RECIBIDO: '{contenido}'")
                elif ttl > 0:
                    paquete["ttl"] = ttl - 1
                    self.reenviar_mensaje_datos(destino, paquete)
                else:
                    print(f"[{self.nombre_nodo}] TTL agotado")
            
        except Exception as e:
            print(f"[{self.nombre_nodo}] Error procesando mensaje: {e}")
    
    def envio_periodico_lsp(self):
        while self.activo:
            time.sleep(INTERVALO_LSP)
            if self.activo:
                print(f"[{self.nombre_nodo}] Enviando LSP periódico")
                self.generar_lsp_propio()
                
                
                lsp_info = self.lsdb.obtener_lsp(self.nombre_nodo)
                if lsp_info:
                    mensaje_lsp = self.crear_mensaje_lsp(
                        self.nombre_nodo,
                        lsp_info['secuencia'],
                        lsp_info['vecinos'],
                        lsp_info['timestamp']
                    )
                    self.flooding_lsp(mensaje_lsp)
    
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
    
    def inicialización_lsr(self):
        time.sleep(TIEMPO_ESPERA_INICIAL)
        
        
        print(f"[{self.nombre_nodo}] Enviando LSP inicial")
        lsp_info = self.lsdb.obtener_lsp(self.nombre_nodo)
        if lsp_info:
            mensaje_lsp = self.crear_mensaje_lsp(
                self.nombre_nodo,
                lsp_info['secuencia'],
                lsp_info['vecinos'],
                lsp_info['timestamp']
            )
            self.flooding_lsp(mensaje_lsp)
        
        
        if self.nombre_nodo == "A":
            time.sleep(10)  
            
            mensaje = self.crear_mensaje_datos(
                destino="D",
                contenido=f"¡Mensaje desde {self.nombre_nodo} usando LSR! - {datetime.now().strftime('%H:%M:%S')}"
            )
            
            print(f"[{self.nombre_nodo}] Enviando mensaje de prueba")
            if "D" in self.tabla_enrutamiento:
                self.reenviar_mensaje_datos("D", mensaje)
            else:
                print(f"[{self.nombre_nodo}] Ruta a D no disponible aún")
    
    def iniciar(self):
        print(f"[{self.nombre_nodo}] Iniciando nodo Link State Routing")
        
        
        hilo_servidor = threading.Thread(target=self.escuchar_conexiones, daemon=True)
        hilo_servidor.start()
        
        
        hilo_lsp_periodico = threading.Thread(target=self.envio_periodico_lsp, daemon=True)
        hilo_lsp_periodico.start()
        
        
        hilo_inicial = threading.Thread(target=self.inicialización_lsr, daemon=True)
        hilo_inicial.start()
        
        try:
            while self.activo:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.nombre_nodo}] Deteniendo nodo")
            self.activo = False
            if self.socket_servidor:
                self.socket_servidor.close()

def main():
    if len(sys.argv) != 3:
        sys.exit(1)
    
    nombre_nodo = sys.argv[1].upper()
    archivo_topologia = sys.argv[2]
    
    
    nodo = LinkStateNode(nombre_nodo, archivo_topologia)
    nodo.iniciar()

if __name__ == "__main__":
    main()