import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import socket
import uuid
import redis
import time
import heapq
from datetime import datetime
from abc import ABC, abstractmethod
from collections import defaultdict


PUERTO_BASE_LOCAL = 5000
TAMANIO_BUFFER = 4096
VALOR_TTL_INICIAL = 5
INTERVALO_LSP = 30
INTERVALO_DV = 10
MAX_DISTANCIA = 16

def safe_get_header_value(headers, key, default=None):
    if isinstance(headers, dict):
        return headers.get(key, default)
    elif isinstance(headers, list):
        if key == "path":
            return headers  
        elif key == "msg_id" or key == "id":
            return None  
        else:
            return default
    else:
        return default

def safe_get_msg_id(paquete):
    headers = paquete.get("headers", [])
    msg_id = safe_get_header_value(headers, "msg_id")
    if not msg_id:
        msg_id = safe_get_header_value(headers, "id")  
    return msg_id

def safe_get_path(paquete):
    headers = paquete.get("headers", [])
    if isinstance(headers, dict):
        return headers.get("path", [])
    elif isinstance(headers, list):
        return headers  
    else:
        return []


class CommunicationMode(ABC):
    @abstractmethod
    def initialize(self):
        pass
    
    @abstractmethod
    def send_message(self, destino, mensaje):
        pass
    
    @abstractmethod
    def start_listening(self, callback):
        pass
    
    @abstractmethod
    def cleanup(self):
        pass
    
    @abstractmethod
    def set_protocol(self, protocol_name):
        pass

class RoutingAlgorithm(ABC):
    def __init__(self, nodo_id, vecinos, communication_mode):
        self.nodo_id = nodo_id
        self.vecinos = vecinos
        self.communication_mode = communication_mode
        self.activo = True
        self.mensajes_procesados = set()
    
    @abstractmethod
    def process_message(self, mensaje):
        pass
    
    @abstractmethod
    def send_initial_messages(self):
        pass
    
    @abstractmethod
    def get_algorithm_name(self):
        pass
    
    @abstractmethod
    def get_protocol_name(self):
        pass



class LocalSocketMode(CommunicationMode):
    def __init__(self, nodo_id):
        self.nodo_id = nodo_id
        self.puerto = PUERTO_BASE_LOCAL + (ord(nodo_id.upper()) - ord('A'))
        self.servidor_socket = None
        self.activo = True
        self.protocol_name = "generic"
        
    def set_protocol(self, protocol_name):
        self.protocol_name = protocol_name
        
    def initialize(self):
        return True
    
    def send_message(self, destino, mensaje):
        try:
            mensaje_con_protocolo = mensaje.copy()
            mensaje_con_protocolo["proto"] = self.protocol_name
            
            puerto_destino = PUERTO_BASE_LOCAL + (ord(destino.upper()) - ord('A'))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("localhost", puerto_destino))
                s.sendall(json.dumps(mensaje_con_protocolo).encode('utf-8'))
            return True
        except Exception as e:
            return False, str(e)
    
    def start_listening(self, callback):
        def escuchar():
            try:
                self.servidor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.servidor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.servidor_socket.bind(("localhost", self.puerto))
                self.servidor_socket.listen(5)
                
                while self.activo:
                    try:
                        conn, _ = self.servidor_socket.accept()
                        datos = conn.recv(TAMANIO_BUFFER).decode('utf-8')
                        conn.close()
                        
                        if datos and callback:
                            callback(datos)
                    except:
                        if self.activo:
                            continue
                        break
            except Exception as e:
                if callback:
                    callback(f"Error en servidor: {e}")
        
        threading.Thread(target=escuchar, daemon=True).start()
        return f"Escuchando en puerto {self.puerto}"
    
    def cleanup(self):
        self.activo = False
        if self.servidor_socket:
            try:
                self.servidor_socket.close()
            except:
                pass

class RedisMode(CommunicationMode):
    def __init__(self, nodo_id, redis_config, channels_config=None):
        self.nodo_id = nodo_id
        self.redis_config = redis_config
        self.redis_client = None
        self.pubsub = None
        self.activo = True
        self.protocol_name = "generic"
        
        if channels_config:
            self.mis_canales = channels_config.get("subscribe", [f"sec20.topologia1.node{nodo_id.lower()}"])
            self.canales_vecinos = channels_config.get("neighbors", {})
        else:
            self.mis_canales = [f"sec20.topologia1.node{nodo_id.lower()}"]
            self.canales_vecinos = {}
    
    def set_protocol(self, protocol_name):
        self.protocol_name = protocol_name
        
    def initialize(self):
        try:
            self.redis_client = redis.Redis(
                host=self.redis_config.get('host', 'localhost'),
                port=self.redis_config.get('port', 6379),
                password=self.redis_config.get('password', ''),
                decode_responses=True
            )
            
            self.redis_client.ping()
            self.pubsub = self.redis_client.pubsub()
            
            for canal in self.mis_canales:
                self.pubsub.subscribe(canal)
            
            return True
        except Exception as e:
            return False, str(e)
    
    def set_neighbor_channels(self, vecinos):
        self.canales_vecinos = {}
        for vecino in vecinos:
            self.canales_vecinos[vecino] = f"sec20.topologia1.node{vecino.lower()}"
    
    def send_message(self, destino, mensaje):
        try:
            if destino.upper() in self.canales_vecinos:
                canal_destino = self.canales_vecinos[destino.upper()]
            else:
                canal_destino = f"sec20.topologia1.node{destino.lower()}"
            
            mensaje_redis = {
                "proto": self.protocol_name,  
                "type": mensaje.get("type", "message"),
                "from": self.nodo_id,
                "to": destino,
                "ttl": mensaje.get("ttl", 5),
                "headers": mensaje.get("headers", {}),  
                "payload": mensaje.get("payload", "")
            }
            
            self.redis_client.publish(canal_destino, json.dumps(mensaje_redis))
            return True
        except Exception as e:
            return False, str(e)
    
    def broadcast_message(self, mensaje):
        try:
            enviados = 0
            for vecino, canal in self.canales_vecinos.items():
                mensaje_redis = {
                    "proto": self.protocol_name,  
                    "type": mensaje.get("type", "message"),
                    "from": self.nodo_id,
                    "to": "broadcast",
                    "ttl": mensaje.get("ttl", 5),
                    "headers": mensaje.get("headers", {}),  
                    "payload": mensaje.get("payload", "")
                }
                
                self.redis_client.publish(canal, json.dumps(mensaje_redis))
                enviados += 1
            return enviados
        except Exception as e:
            return False, str(e)
    
    def start_listening(self, callback):
        def escuchar():
            try:
                for mensaje in self.pubsub.listen():
                    if not self.activo:
                        break
                    if mensaje['type'] == 'message':
                        if callback:
                            callback(mensaje['data'])
            except Exception as e:
                if callback and self.activo:
                    callback(f"Error Redis: {e}")
        
        threading.Thread(target=escuchar, daemon=True).start()
        return f"Escuchando canales Redis: {', '.join(self.mis_canales)}"
    
    def cleanup(self):
        self.activo = False
        if self.pubsub:
            try:
                self.pubsub.close()
            except:
                pass



class FloodingAlgorithm(RoutingAlgorithm):
    def get_algorithm_name(self):
        return "flooding"
    
    def get_protocol_name(self):
        return "flooding"
    
    def process_message(self, paquete):
        tipo = paquete.get("type", "")
        origen = paquete.get("from", "")
        destino = paquete.get("to", "")
        contenido = paquete.get("payload", "")
        ttl = paquete.get("ttl", 0)
        
        if destino == self.nodo_id:
            return f"MENSAJE RECIBIDO de {origen}: '{contenido}'"
        elif ttl > 1:
            paquete["ttl"] = ttl - 1
            paquete["proto"] = self.get_protocol_name()  
            self.flood_message(paquete, origen)
            return f"Mensaje reenviado por flooding (TTL: {ttl-1})"
        else:
            return "TTL agotado, mensaje descartado"
    
    def flood_message(self, mensaje, origen=None):
        mensaje["proto"] = self.get_protocol_name()
        
        if isinstance(self.communication_mode, RedisMode):
            self.communication_mode.broadcast_message(mensaje)
        else:
            for vecino in self.vecinos:
                if vecino != origen:
                    self.communication_mode.send_message(vecino, mensaje)
    
    def send_initial_messages(self):
        if self.nodo_id == "A":
            time.sleep(3)
            
            mensaje = {
                "proto": self.get_protocol_name(),
                "type": "message",
                "from": self.nodo_id,
                "to": "D",
                "ttl": VALOR_TTL_INICIAL,
                "headers": [self.nodo_id],  
                "payload": f"Mensaje de prueba desde {self.nodo_id} usando {self.get_algorithm_name().upper()}!"
            }
            self.flood_message(mensaje)

class LinkStateAlgorithm(RoutingAlgorithm):
    def __init__(self, nodo_id, vecinos, communication_mode):
        super().__init__(nodo_id, vecinos, communication_mode)
        self.lsdb = {}
        self.tabla_enrutamiento = {}
        self.secuencia_lsp = 0
        self.lock = threading.Lock()
        self.vecinos_detectados = set()
        
        self.generar_lsp_propio()
        threading.Thread(target=self.envio_periodico_lsp, daemon=True).start()
    
    def get_algorithm_name(self):
        return "link_state"
    
    def get_protocol_name(self):
        return "lsr"
    
    def generar_lsp_propio(self):
        with self.lock:
            self.secuencia_lsp += 1
            timestamp = time.time()
            
            self.lsdb[self.nodo_id] = {
                'secuencia': self.secuencia_lsp,
                'vecinos': self.vecinos,
                'timestamp': timestamp
            }
    
    def process_message(self, paquete):
        tipo = paquete.get("type", "")
        origen = paquete.get("from", "")
        destino = paquete.get("to", "")
        contenido = paquete.get("payload", "")
        ttl = paquete.get("ttl", 0)
        
        
        if origen in self.vecinos and origen != self.nodo_id:
            if origen not in self.vecinos_detectados:
                self.vecinos_detectados.add(origen)
        
        
        if tipo == "lsp" or tipo == "info":
            return self.procesar_lsp(paquete)
        elif tipo == "hello":
            self.vecinos_detectados.add(origen)
            return f"HELLO procesado de {origen}"
        elif tipo == "message":
            if destino == self.nodo_id:
                return f"MENSAJE RECIBIDO de {origen}: '{contenido}'"
            elif ttl > 1:
                return self.reenviar_mensaje(destino, paquete)
            else:
                return "TTL agotado"
        
        return f"Mensaje procesado: {tipo} de {origen}"
    
    def procesar_lsp(self, paquete):
        payload = paquete.get("payload", {})
        
        
        if isinstance(payload, dict):
            nodo_origen = payload.get("nodo_origen", paquete.get("from"))
            secuencia = payload.get("secuencia", payload.get("sequence", 1))
            vecinos = payload.get("vecinos", payload.get("neighbors", []))
            timestamp = payload.get("timestamp", time.time())
        else:
            nodo_origen = paquete.get("from")
            secuencia = 1
            vecinos = []
            timestamp = time.time()
            
            
            try:
                if isinstance(payload, str):
                    payload_data = json.loads(payload)
                    vecinos = payload_data.get("vecinos", payload_data.get("neighbors", []))
                    secuencia = payload_data.get("secuencia", payload_data.get("sequence", 1))
            except:
                pass
        
        with self.lock:
            lsp_nuevo = (nodo_origen not in self.lsdb or 
                        secuencia > self.lsdb[nodo_origen]['secuencia'])
            
            if lsp_nuevo:
                self.lsdb[nodo_origen] = {
                    'secuencia': secuencia,
                    'vecinos': vecinos,
                    'timestamp': timestamp
                }
                
                self.calcular_dijkstra()
                
                
                if paquete.get("ttl", 0) > 1:
                    paquete["ttl"] = paquete["ttl"] - 1
                    paquete["proto"] = self.get_protocol_name()
                    if isinstance(self.communication_mode, RedisMode):
                        self.communication_mode.broadcast_message(paquete)
                    else:
                        for vecino in self.vecinos:
                            if vecino != paquete.get("from"):
                                self.communication_mode.send_message(vecino, paquete)
                
                return f"LSP/INFO de {nodo_origen} procesado y reenviado"
            else:
                return f"LSP/INFO de {nodo_origen} ignorado (más antiguo)"
    
    def calcular_dijkstra(self):
        grafo = defaultdict(dict)
        
        
        for nodo, info in self.lsdb.items():
            vecinos_nodo = info.get('vecinos', [])
            for vecino in vecinos_nodo:
                grafo[nodo][vecino] = 1
        
        if not grafo or self.nodo_id not in grafo:
            return
        
        
        distancias = {nodo: float('inf') for nodo in grafo}
        distancias[self.nodo_id] = 0
        predecesores = {}
        visitados = set()
        cola = [(0, self.nodo_id)]
        
        while cola:
            dist_actual, nodo_actual = heapq.heappop(cola)
            
            if nodo_actual in visitados:
                continue
            
            visitados.add(nodo_actual)
            
            for vecino, peso in grafo.get(nodo_actual, {}).items():
                if vecino not in visitados:
                    nueva_dist = dist_actual + peso
                    if nueva_dist < distancias[vecino]:
                        distancias[vecino] = nueva_dist
                        predecesores[vecino] = nodo_actual
                        heapq.heappush(cola, (nueva_dist, vecino))
        
        
        nueva_tabla = {}
        for destino, dist in distancias.items():
            if destino != self.nodo_id and dist != float('inf'):
                nodo_temp = destino
                while predecesores.get(nodo_temp) != self.nodo_id and nodo_temp in predecesores:
                    nodo_temp = predecesores[nodo_temp]
                
                if predecesores.get(nodo_temp) == self.nodo_id:
                    nueva_tabla[destino] = {
                        'next_hop': nodo_temp,
                        'distance': int(dist)
                    }
        
        self.tabla_enrutamiento = nueva_tabla
    
    def reenviar_mensaje(self, destino, paquete):
        if destino in self.tabla_enrutamiento:
            info = self.tabla_enrutamiento[destino]
            siguiente_salto = info['next_hop']
            paquete["ttl"] = paquete["ttl"] - 1
            paquete["proto"] = self.get_protocol_name()  
            
            self.communication_mode.send_message(siguiente_salto, paquete)
            return f"Mensaje reenviado a {destino} via {siguiente_salto}"
        else:
            return f"No hay ruta conocida a {destino}"
    
    def enviar_lsp(self):
        lsp_info = self.lsdb.get(self.nodo_id)
        if lsp_info:
            
            mensaje_lsp = {
                "proto": self.get_protocol_name(),
                "type": "info",
                "from": self.nodo_id,
                "to": "broadcast",
                "ttl": 15,
                "headers": {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().isoformat(),
                    "lsp_origen": self.nodo_id,
                    "lsp_secuencia": lsp_info['secuencia']
                },
                "payload": {
                    "nodo_origen": self.nodo_id,
                    "secuencia": lsp_info['secuencia'],
                    "vecinos": lsp_info['vecinos'],
                    "timestamp": lsp_info['timestamp']
                }
            }
            
            if isinstance(self.communication_mode, RedisMode):
                self.communication_mode.broadcast_message(mensaje_lsp)
            else:
                for vecino in self.vecinos:
                    self.communication_mode.send_message(vecino, mensaje_lsp)
    
    def envio_periodico_lsp(self):
        while self.activo:
            time.sleep(INTERVALO_LSP)
            if self.activo:
                self.generar_lsp_propio()
                self.enviar_lsp()
    
    def send_initial_messages(self):
        time.sleep(2)
        self.enviar_lsp()
        
        
        time.sleep(1)
        hello_msg = {
            "proto": self.get_protocol_name(),
            "type": "hello",
            "from": self.nodo_id,
            "to": "broadcast",
            "ttl": 1,
            "headers": {"id": str(uuid.uuid4())[:8]},
            "payload": "hello_from_" + self.nodo_id
        }
        
        if isinstance(self.communication_mode, RedisMode):
            self.communication_mode.broadcast_message(hello_msg)
        
        
        if self.nodo_id == "A":
            time.sleep(10)
            
            mensaje = {
                "proto": self.get_protocol_name(),
                "type": "message",
                "from": self.nodo_id,
                "to": "D",
                "ttl": 15,
                "headers": {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().isoformat()
                },
                "payload": f"Mensaje de prueba desde {self.nodo_id} usando {self.get_algorithm_name().upper()}!"
            }
            
            if "D" in self.tabla_enrutamiento:
                self.reenviar_mensaje("D", mensaje)
            else:
                if isinstance(self.communication_mode, RedisMode):
                    self.communication_mode.broadcast_message(mensaje)

class DistanceVectorAlgorithm(RoutingAlgorithm):
    def __init__(self, nodo_id, vecinos, communication_mode):
        super().__init__(nodo_id, vecinos, communication_mode)
        self.tabla_enrutamiento = {}
        self.tablas_vecinos = defaultdict(dict)
        self.lock = threading.Lock()
        
        self.inicializar_tabla()
        threading.Thread(target=self.actualizacion_periodica, daemon=True).start()
    
    def get_algorithm_name(self):
        return "distance_vector"
    
    def get_protocol_name(self):
        return "dvr"
    
    def inicializar_tabla(self):
        with self.lock:
            self.tabla_enrutamiento[self.nodo_id] = {
                'distance': 0,
                'next_hop': self.nodo_id
            }
            
            for vecino in self.vecinos:
                self.tabla_enrutamiento[vecino] = {
                    'distance': 1,
                    'next_hop': vecino
                }
    
    def process_message(self, paquete):
        tipo = paquete.get("type", "")
        origen = paquete.get("from", "")
        destino = paquete.get("to", "")
        contenido = paquete.get("payload", "")
        ttl = paquete.get("ttl", 0)
        
        if tipo == "distance_vector":
            return self.procesar_vector(origen, contenido)
        elif tipo == "message":
            if destino == self.nodo_id:
                return f"MENSAJE RECIBIDO de {origen}: '{contenido}'"
            elif ttl > 1:
                return self.reenviar_mensaje(destino, paquete)
            else:
                return "TTL agotado"
        
        return f"Mensaje procesado: {tipo} de {origen}"
    
    def procesar_vector(self, vecino, vector_distancias):
        with self.lock:
            self.tablas_vecinos[vecino] = vector_distancias
            tabla_actualizada = False
            
            for destino, distancia_vecino in vector_distancias.items():
                if destino == self.nodo_id:
                    continue
                
                distancia_via_vecino = 1 + distancia_vecino
                
                if (destino not in self.tabla_enrutamiento or 
                    distancia_via_vecino < self.tabla_enrutamiento[destino]['distance']):
                    
                    self.tabla_enrutamiento[destino] = {
                        'distance': distancia_via_vecino,
                        'next_hop': vecino
                    }
                    tabla_actualizada = True
            
            if tabla_actualizada:
                self.enviar_vector()
        
        return f"Vector de {vecino} procesado"
    
    def reenviar_mensaje(self, destino, paquete):
        with self.lock:
            if destino in self.tabla_enrutamiento:
                info = self.tabla_enrutamiento[destino]
                if info['distance'] < MAX_DISTANCIA:
                    siguiente_salto = info['next_hop']
                    paquete["ttl"] = paquete["ttl"] - 1
                    paquete["proto"] = self.get_protocol_name()  
                    self.communication_mode.send_message(siguiente_salto, paquete)
                    return f"Mensaje reenviado a {destino} via {siguiente_salto}"
                else:
                    return f"Destino {destino} inalcanzable"
            else:
                return f"No hay ruta conocida a {destino}"
    
    def enviar_vector(self):
        with self.lock:
            vector_distancias = {}
            for destino, info in self.tabla_enrutamiento.items():
                if info['distance'] < MAX_DISTANCIA:
                    vector_distancias[destino] = info['distance']
        
        mensaje = {
            "proto": self.get_protocol_name(),
            "type": "distance_vector",
            "from": self.nodo_id,
            "to": "broadcast",
            "ttl": 1,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat()
            },
            "payload": vector_distancias
        }
        
        if isinstance(self.communication_mode, RedisMode):
            self.communication_mode.broadcast_message(mensaje)
        else:
            for vecino in self.vecinos:
                self.communication_mode.send_message(vecino, mensaje)
    
    def actualizacion_periodica(self):
        while self.activo:
            time.sleep(INTERVALO_DV)
            if self.activo:
                self.enviar_vector()
    
    def send_initial_messages(self):
        time.sleep(3)
        self.enviar_vector()
        
        if self.nodo_id == "A":
            time.sleep(8)
            
            mensaje = {
                "proto": self.get_protocol_name(),
                "type": "message",
                "from": self.nodo_id,
                "to": "D",
                "ttl": 15,
                "headers": {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().isoformat()
                },
                "payload": f"Mensaje de prueba desde {self.nodo_id} usando {self.get_algorithm_name().upper()}!"
            }
            
            with self.lock:
                if "D" in self.tabla_enrutamiento and self.tabla_enrutamiento["D"]["distance"] < MAX_DISTANCIA:
                    self.reenviar_mensaje("D", mensaje)



class EnhancedNetworkGUI:
    def __init__(self):
        self.ventana = tk.Tk()
        self.ventana.title("Router GUI")
        self.ventana.geometry("900x750")
        
        self.nodo_id = "A"
        self.vecinos = ["B", "C", "D"]
        self.communication_mode = None
        self.routing_algorithm = None
        self.mensajes_recibidos = set()
        
        self.configuracion_redis = {
            'host': 'localhost',
            'port': 6379,
            'password': ''
        }
        
        self.configuracion_canales = {
            'subscribe': [],
            'neighbors': {}
        }
        
        self.topologia_completa = {}
        
        self.crear_interfaz()
    
    def crear_mensaje_compatible(self, tipo, destino, contenido, protocolo):
        if protocolo == "flooding":
            headers = [self.nodo_id]
        else:
            headers = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "path": [self.nodo_id]
            }
        
        return {
            "proto": protocolo,
            "type": tipo,
            "from": self.nodo_id,
            "to": destino,
            "ttl": VALOR_TTL_INICIAL,
            "headers": headers,
            "payload": contenido
        }
    
    def crear_interfaz(self):
        main_frame = ttk.Frame(self.ventana, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        self.ventana.columnconfigure(0, weight=1)
        self.ventana.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        config_frame = ttk.LabelFrame(main_frame, text="Configuración", padding=10)
        config_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,10))
        config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(config_frame, text="Comunicación:").grid(row=0, column=0, sticky="w")
        self.modo_var = tk.StringVar(value="local")
        modo_frame = ttk.Frame(config_frame)
        modo_frame.grid(row=0, column=1, sticky="ew")
        
        ttk.Radiobutton(modo_frame, text="Local (Sockets)", variable=self.modo_var, 
                       value="local", command=self.cambiar_modo).pack(side="left")
        ttk.Radiobutton(modo_frame, text="Redis", variable=self.modo_var, 
                       value="redis", command=self.cambiar_modo).pack(side="left", padx=(20,0))
        
        ttk.Label(config_frame, text="Algoritmo:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.algoritmo_var = tk.StringVar(value="flooding")
        algoritmo_frame = ttk.Frame(config_frame)
        algoritmo_frame.grid(row=1, column=1, sticky="ew", pady=(5,0))
        
        ttk.Radiobutton(algoritmo_frame, text="Flooding", variable=self.algoritmo_var, 
                       value="flooding").pack(side="left")
        ttk.Radiobutton(algoritmo_frame, text="Link State", variable=self.algoritmo_var, 
                       value="link_state").pack(side="left", padx=(20,0))
        ttk.Radiobutton(algoritmo_frame, text="Distance Vector", variable=self.algoritmo_var, 
                       value="distance_vector").pack(side="left", padx=(20,0))
        
        ttk.Label(config_frame, text="ID Nodo:").grid(row=2, column=0, sticky="w", pady=(5,0))
        self.nodo_entry = ttk.Entry(config_frame, width=10)
        self.nodo_entry.grid(row=2, column=1, sticky="w", pady=(5,0))
        self.nodo_entry.insert(0, self.nodo_id)
        
        ttk.Label(config_frame, text="Vecinos:").grid(row=3, column=0, sticky="w", pady=(5,0))
        self.vecinos_entry = ttk.Entry(config_frame, width=30)
        self.vecinos_entry.grid(row=3, column=1, sticky="ew", pady=(5,0))
        self.vecinos_entry.insert(0, ",".join(self.vecinos))
        
        self.redis_frame = ttk.LabelFrame(config_frame, text="Configuración Redis")
        
        ttk.Label(self.redis_frame, text="Host:").grid(row=0, column=0, sticky="w", padx=(5,5))
        self.redis_host_entry = ttk.Entry(self.redis_frame, width=20)
        self.redis_host_entry.grid(row=0, column=1, padx=(0,10))
        self.redis_host_entry.insert(0, self.configuracion_redis['host'])
        
        ttk.Label(self.redis_frame, text="Puerto:").grid(row=0, column=2, sticky="w", padx=(5,5))
        self.redis_port_entry = ttk.Entry(self.redis_frame, width=10)
        self.redis_port_entry.grid(row=0, column=3, padx=(0,10))
        self.redis_port_entry.insert(0, str(self.configuracion_redis['port']))
        
        ttk.Label(self.redis_frame, text="Password:").grid(row=1, column=0, sticky="w", padx=(5,5), pady=(5,0))
        self.redis_pass_entry = ttk.Entry(self.redis_frame, width=20, show="*")
        self.redis_pass_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(5,0), padx=(0,10))
        self.redis_pass_entry.insert(0, self.configuracion_redis['password'])
        
        botones_config_frame = ttk.Frame(config_frame)
        botones_config_frame.grid(row=5, column=0, columnspan=2, pady=(10,0))
        
        ttk.Button(botones_config_frame, text="Cargar Config JSON", 
                  command=self.cargar_configuracion).pack(side="left", padx=(0,5))
        ttk.Button(botones_config_frame, text="Test Redis", 
                  command=self.probar_conectividad_redis).pack(side="left", padx=(0,5))
        ttk.Button(botones_config_frame, text="Conectar", 
                  command=self.conectar).pack(side="left", padx=(0,5))
        self.status_label = ttk.Label(botones_config_frame, text="Desconectado", foreground="red")
        self.status_label.pack(side="left", padx=(10,0))
        
        mensaje_frame = ttk.LabelFrame(main_frame, text="Enviar Mensaje", padding=10)
        mensaje_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0,10))
        mensaje_frame.columnconfigure(1, weight=1)
        
        ttk.Label(mensaje_frame, text="Destino:").grid(row=0, column=0, sticky="w")
        self.destino_combo = ttk.Combobox(mensaje_frame, values=self.vecinos, width=15)
        self.destino_combo.grid(row=0, column=1, sticky="w")
        
        ttk.Label(mensaje_frame, text="Tipo:").grid(row=0, column=2, sticky="w", padx=(10,5))
        self.tipo_combo = ttk.Combobox(mensaje_frame, values=["message", "hello", "info", "lsp", "distance_vector"], width=15)
        self.tipo_combo.grid(row=0, column=3, sticky="w")
        self.tipo_combo.set("message")
        
        ttk.Label(mensaje_frame, text="Mensaje:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.mensaje_entry = ttk.Entry(mensaje_frame, width=50)
        self.mensaje_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(5,0))
        self.mensaje_entry.bind("<Return>", lambda e: self.enviar_mensaje())
        
        ttk.Button(mensaje_frame, text="Enviar", command=self.enviar_mensaje).grid(row=1, column=3, pady=(5,0), padx=(5,0))
        
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0,10))
        
        ttk.Button(control_frame, text="Mostrar Tabla Enrutamiento", command=self.mostrar_tabla_enrutamiento).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Mostrar Estado", command=self.mostrar_estado).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Limpiar Log", command=self.limpiar_log).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Desconectar", command=self.desconectar).pack(side="right")
        
        log_frame = ttk.LabelFrame(main_frame, text="Log de Mensajes", padding=5)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, width=80, height=20, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        self.log_text.tag_configure("enviado", foreground="blue")
        self.log_text.tag_configure("recibido", foreground="green")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("sistema", foreground="purple")
        self.log_text.tag_configure("algoritmo", foreground="orange")
        
        self.cambiar_modo()
    
    def cambiar_modo(self):
        modo = self.modo_var.get()
        
        if modo == "redis":
            self.redis_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10,0))
            self.redis_frame.columnconfigure(1, weight=1)
            self.redis_frame.columnconfigure(3, weight=1)
        else:
            self.redis_frame.grid_remove()
        
        if self.communication_mode:
            self.desconectar()
    
    def conectar(self):
        try:
            self.nodo_id = self.nodo_entry.get().strip().upper()
            vecinos_str = self.vecinos_entry.get().strip()
            self.vecinos = [v.strip().upper() for v in vecinos_str.split(",") if v.strip()]
            
            if not self.nodo_id:
                messagebox.showerror("Error", "ID de nodo requerido")
                return
            
            if self.communication_mode:
                self.desconectar()
            
            modo = self.modo_var.get()
            algoritmo = self.algoritmo_var.get()
            
            self.log_mensaje(f"[{self.nodo_id}] Conectando en modo {modo.upper()} con algoritmo {algoritmo.upper()}", "sistema")
            
            if modo == "local":
                self.communication_mode = LocalSocketMode(self.nodo_id)
            elif modo == "redis":
                self.configuracion_redis = {
                    'host': self.redis_host_entry.get().strip(),
                    'port': int(self.redis_port_entry.get().strip()),
                    'password': self.redis_pass_entry.get().strip()
                }
                
                channels_config = None
                if self.configuracion_canales.get('subscribe') or self.configuracion_canales.get('neighbors'):
                    channels_config = self.configuracion_canales
                else:
                    channels_config = {
                        'subscribe': [f"sec20.topologia1.node{self.nodo_id.lower()}"],
                        'neighbors': {vecino: f"sec20.topologia1.node{vecino.lower()}" for vecino in self.vecinos}
                    }
                
                self.communication_mode = RedisMode(self.nodo_id, self.configuracion_redis, channels_config)
                self.communication_mode.set_neighbor_channels(self.vecinos)
            
            result = self.communication_mode.initialize()
            if isinstance(result, tuple) and not result[0]:
                raise Exception(result[1])
            
            if algoritmo == "flooding":
                self.routing_algorithm = FloodingAlgorithm(self.nodo_id, self.vecinos, self.communication_mode)
            elif algoritmo == "link_state":
                self.routing_algorithm = LinkStateAlgorithm(self.nodo_id, self.vecinos, self.communication_mode)
            elif algoritmo == "distance_vector":
                self.routing_algorithm = DistanceVectorAlgorithm(self.nodo_id, self.vecinos, self.communication_mode)
            
            if hasattr(self.routing_algorithm, 'get_protocol_name'):
                protocol_name = self.routing_algorithm.get_protocol_name()
                self.communication_mode.set_protocol(protocol_name)
                self.log_mensaje(f"[{self.nodo_id}] Protocolo configurado: {protocol_name}", "sistema")
            
            status_msg = self.communication_mode.start_listening(self.procesar_mensaje_recibido)
            
            threading.Thread(target=self.routing_algorithm.send_initial_messages, daemon=True).start()
            
            self.destino_combo.config(values=self.vecinos)
            self.status_label.config(text=f"Conectado ({modo}/{algoritmo})", foreground="green")
            
            self.log_mensaje(f"[{self.nodo_id}] ✓ CONECTADO - {modo.upper()}/{algoritmo.upper()}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] Vecinos: {', '.join(self.vecinos)}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] {status_msg}", "sistema")
            
        except Exception as e:
            messagebox.showerror("Error de Conexión", str(e))
            self.status_label.config(text="Error de conexión", foreground="red")
            self.log_mensaje(f"[{self.nodo_id}] ✗ ERROR: {e}", "error")
    
    def desconectar(self):
        if self.routing_algorithm:
            self.routing_algorithm.activo = False
            self.routing_algorithm = None
        
        if self.communication_mode:
            self.communication_mode.cleanup()
            self.communication_mode = None
        
        self.status_label.config(text="Desconectado", foreground="red")
        self.log_mensaje("Desconectado", "sistema")
    
    def enviar_mensaje(self):
        if not self.communication_mode:
            messagebox.showwarning("Advertencia", "No conectado")
            return
        
        destino = self.destino_combo.get().strip().upper()
        contenido = self.mensaje_entry.get().strip()
        tipo = self.tipo_combo.get()
        
        if not destino or not contenido:
            messagebox.showwarning("Advertencia", "Destino y mensaje requeridos")
            return
        
        protocol_name = "gui_manual"  
        if hasattr(self.routing_algorithm, 'get_protocol_name'):
            protocol_name = self.routing_algorithm.get_protocol_name()
        
        mensaje = self.crear_mensaje_compatible(tipo, destino, contenido, protocol_name)
        
        result = self.communication_mode.send_message(destino, mensaje)
        
        if isinstance(result, tuple):
            success, error = result
            if success:
                self.log_mensaje(f"→ Enviado a {destino} ({protocol_name}/{tipo}): {contenido}", "enviado")
                self.mensaje_entry.delete(0, tk.END)
            else:
                self.log_mensaje(f"✗ Error enviando a {destino}: {error}", "error")
        elif result:
            self.log_mensaje(f"→ Enviado a {destino} ({protocol_name}/{tipo}): {contenido}", "enviado")
            self.mensaje_entry.delete(0, tk.END)
        else:
            self.log_mensaje(f"✗ Error enviando a {destino}", "error")
    
    def procesar_mensaje_recibido(self, datos):
        try:
            paquete = json.loads(datos)
            
            origen = paquete.get("from", "desconocido")
            destino = paquete.get("to", "")
            contenido = paquete.get("payload", "")
            tipo = paquete.get("type", "message")
            ttl = paquete.get("ttl", 0)
            proto = paquete.get("proto", "unknown")
            
            msg_id = safe_get_msg_id(paquete)
            
            if msg_id and msg_id in self.mensajes_recibidos:
                return
            if msg_id:
                self.mensajes_recibidos.add(msg_id)
            
            if origen == self.nodo_id:
                return
            
            self.log_mensaje(f"[{self.nodo_id}] Recibido: {proto} | {tipo} | {origen} → {destino} | TTL:{ttl}", "recibido")
            
            if self.routing_algorithm:
                resultado = self.routing_algorithm.process_message(paquete)
                if resultado:
                    self.log_mensaje(f"[{self.nodo_id}] {resultado}", "algoritmo")
            else:
                self.log_mensaje(f"[{self.nodo_id}] Sin algoritmo configurado", "error")
                
        except json.JSONDecodeError as e:
            self.log_mensaje(f"[{self.nodo_id}] ERROR JSON: {e}", "error")
        except Exception as e:
            self.log_mensaje(f"[{self.nodo_id}] ERROR procesando: {e}", "error")
    
    def mostrar_tabla_enrutamiento(self):
        if not self.communication_mode:
            messagebox.showwarning("Advertencia", "No conectado")
            return
        
        if not self.routing_algorithm:
            self.log_mensaje("No hay algoritmo de enrutamiento configurado", "error")
            return
        
        algoritmo_nombre = self.routing_algorithm.get_algorithm_name()
        
        if hasattr(self.routing_algorithm, 'tabla_enrutamiento'):
            tabla = self.routing_algorithm.tabla_enrutamiento
            
            texto = f"\n[{self.nodo_id}] TABLA DE ENRUTAMIENTO - {algoritmo_nombre.upper()}:\n"
            texto += "-" * 60 + "\n"
            
            if not tabla:
                texto += "*** TABLA VACÍA ***\n"
                if hasattr(self.routing_algorithm, 'lsdb'):
                    lsdb = self.routing_algorithm.lsdb
                    texto += f"LSDB contiene: {len(lsdb)} entradas: {list(lsdb.keys())}\n"
                    if hasattr(self.routing_algorithm, 'vecinos_detectados'):
                        texto += f"Vecinos detectados: {list(self.routing_algorithm.vecinos_detectados)}\n"
                    
            else:
                if algoritmo_nombre == "link_state":
                    texto += "Destino | Siguiente Salto | Distancia\n"
                    texto += "-" * 60 + "\n"
                    
                    for destino, info in sorted(tabla.items()):
                        texto += f"{destino:^7} | {info['next_hop']:^14} | {info['distance']:^9}\n"
                        
                elif algoritmo_nombre == "distance_vector":
                    texto += "Destino | Distancia | Siguiente Salto\n"
                    texto += "-" * 60 + "\n"
                    
                    for destino, info in sorted(tabla.items()):
                        distancia = info['distance']
                        siguiente = info['next_hop']
                        distancia_str = str(distancia) if distancia < MAX_DISTANCIA else "∞"
                        texto += f"{destino:^7} | {distancia_str:^9} | {siguiente:^14}\n"
            
            texto += "-" * 60
            self.log_mensaje(texto, "sistema")
        else:
            self.log_mensaje(f"[{self.nodo_id}] Algoritmo {algoritmo_nombre} no tiene tabla de enrutamiento", "sistema")
    
    def mostrar_estado(self):
        modo = self.modo_var.get()
        algoritmo = self.algoritmo_var.get()
        
        estado = f"Estado del Nodo: {self.nodo_id}\n"
        estado += f"Modo: {modo.upper()}\n"
        estado += f"Algoritmo: {algoritmo.upper()}\n"
        
        if self.routing_algorithm:
            if hasattr(self.routing_algorithm, 'get_protocol_name'):
                estado += f"Protocolo: {self.routing_algorithm.get_protocol_name()}\n"
            
            if hasattr(self.routing_algorithm, 'lsdb'):
                estado += f"LSDB entradas: {len(self.routing_algorithm.lsdb)}\n"
            
            if hasattr(self.routing_algorithm, 'vecinos_detectados'):
                estado += f"Vecinos detectados: {list(self.routing_algorithm.vecinos_detectados)}\n"
            
            if hasattr(self.routing_algorithm, 'tabla_enrutamiento'):
                tabla = self.routing_algorithm.tabla_enrutamiento
                estado += f"Rutas en tabla: {len(tabla)}\n"
                if tabla:
                    estado += "Destinos alcanzables: " + ", ".join(tabla.keys()) + "\n"
        
        estado += f"Vecinos configurados: {', '.join(self.vecinos)}\n"
        estado += f"Mensajes recibidos: {len(self.mensajes_recibidos)}\n"
        
        if modo == "redis":
            estado += f"\nConfiguración Redis:\n"
            estado += f"  Host: {self.configuracion_redis['host']}\n"
            estado += f"  Puerto: {self.configuracion_redis['port']}\n"
            estado += f"  Password: {'*' * len(self.configuracion_redis.get('password', ''))}\n"
            
            if hasattr(self.communication_mode, 'canales_vecinos'):
                estado += f"\nCanales vecinos configurados: {len(self.communication_mode.canales_vecinos)}\n"
                for vecino, canal in self.communication_mode.canales_vecinos.items():
                    estado += f"  • {vecino} → {canal}\n"
                    
        elif modo == "local":
            puerto = PUERTO_BASE_LOCAL + (ord(self.nodo_id) - ord('A'))
            estado += f"\nPuerto Local: {puerto}\n"
        
        if self.topologia_completa:
            estado += f"\nTopología completa:\n"
            for nodo, vecinos_nodo in self.topologia_completa.items():
                estado += f"  • {nodo}: {', '.join(vecinos_nodo)}\n"
        
        self.log_mensaje(estado, "sistema")
    
    def cargar_configuracion(self):
        archivo = filedialog.askopenfilename(
            title="Seleccionar archivo de configuración",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if archivo:
            try:
                with open(archivo, 'r') as f:
                    config = json.load(f)
                
                if 'node_id' in config:
                    self.nodo_entry.delete(0, tk.END)
                    self.nodo_entry.insert(0, config['node_id'])
                
                if 'topology' in config:
                    self.topologia_completa = config['topology']
                    if config.get('node_id') in self.topologia_completa:
                        vecinos = self.topologia_completa[config['node_id']]
                        self.vecinos_entry.delete(0, tk.END)
                        self.vecinos_entry.insert(0, ",".join(vecinos))
                
                if 'redis' in config:
                    redis_config = config['redis']
                    self.redis_host_entry.delete(0, tk.END)
                    self.redis_host_entry.insert(0, redis_config.get('host', 'localhost'))
                    
                    self.redis_port_entry.delete(0, tk.END)
                    self.redis_port_entry.insert(0, str(redis_config.get('port', 6379)))
                    
                    self.redis_pass_entry.delete(0, tk.END)
                    self.redis_pass_entry.insert(0, redis_config.get('password', ''))
                    
                    self.modo_var.set("redis")
                    self.cambiar_modo()
                
                if 'channels' in config:
                    self.configuracion_canales = config['channels']
                
                self.configuracion_redis.update(config.get('redis', {}))
                
                self.log_mensaje("Configuración cargada exitosamente", "sistema")
                
            except Exception as e:
                messagebox.showerror("Error", f"Error cargando configuración: {e}")
    
    def probar_conectividad_redis(self):
        try:
            test_client = redis.Redis(
                host=self.redis_host_entry.get().strip(),
                port=int(self.redis_port_entry.get().strip()),
                password=self.redis_pass_entry.get().strip(),
                decode_responses=True,
                socket_timeout=5
            )
            
            test_client.ping()
            test_client.close()
            
            self.log_mensaje("Conectividad Redis OK", "sistema")
            messagebox.showinfo("Conectividad", "Conexión a Redis exitosa")
            
        except Exception as e:
            self.log_mensaje(f"Error conectividad Redis: {e}", "error")
            messagebox.showerror("Error", f"No se pudo conectar a Redis: {e}")
    
    def limpiar_log(self):
        self.log_text.delete(1.0, tk.END)
        self.mensajes_recibidos.clear()
    
    def log_mensaje(self, mensaje, categoria="normal"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        mensaje_completo = f"[{timestamp}] {mensaje}\n"
        
        self.log_text.insert(tk.END, mensaje_completo, categoria)
        self.log_text.see(tk.END)
        
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 1000:
            self.log_text.delete('1.0', '100.0')
    
    def iniciar(self):
        try:
            self.ventana.protocol("WM_DELETE_WINDOW", self.cerrar_aplicacion)
            self.ventana.mainloop()
        except KeyboardInterrupt:
            self.cerrar_aplicacion()
    
    def cerrar_aplicacion(self):
        if self.routing_algorithm:
            self.routing_algorithm.activo = False
        if self.communication_mode:
            self.desconectar()
        self.ventana.quit()
        self.ventana.destroy()

def main():
    import sys
    
    nodo_inicial = sys.argv[1].upper() if len(sys.argv) > 1 else "A"
    vecinos_inicial = sys.argv[2].split(",") if len(sys.argv) > 2 else ["B", "C", "D"]
    vecinos_inicial = [v.strip().upper() for v in vecinos_inicial]
    
    gui = EnhancedNetworkGUI()
    
    gui.nodo_entry.delete(0, tk.END)
    gui.nodo_entry.insert(0, nodo_inicial)
    
    gui.vecinos_entry.delete(0, tk.END)
    gui.vecinos_entry.insert(0, ",".join(vecinos_inicial))
    
    gui.log_mensaje(f"GUI iniciada - Nodo: {nodo_inicial}, Vecinos: {', '.join(vecinos_inicial)}", "sistema")
    
    gui.iniciar()

if __name__ == "__main__":
    main()