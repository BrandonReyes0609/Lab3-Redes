import json
import time
import threading
import heapq
import uuid
from collections import defaultdict
from datetime import datetime


try:
    from redis_base_node import ConfigurableRedisNode, FlexiblePacket
    HAS_BASE_NODE = True
except ImportError:
    HAS_BASE_NODE = False
    import redis

class EnhancedRedisLSRNode:
    def __init__(self, config_file_or_params):
        
        if isinstance(config_file_or_params, str):
            
            try:
                with open(config_file_or_params, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.init_from_config(config)
            except Exception as e:
                print(f"Error cargando config: {e}")
                self.init_default()
        elif isinstance(config_file_or_params, dict):
            
            self.init_from_config(config_file_or_params)
        else:
            self.init_default()
        
        
        self.lsdb = {}  
        self.tabla_enrutamiento = {}
        self.secuencia_lsp = 0
        self.vecinos_activos = set()
        
        
        self.activo = True
        self.mensajes_procesados = set()
        self.lock = threading.Lock()
        
        
        self.redis_client = None
        self.pubsub = None
        
        print(f"[{self.node_id}] Enhanced LSR Node inicializado")
        print(f"[{self.node_id}] Vecinos configurados: {self.vecinos}")
        print(f"[{self.node_id}] Canales: Subscribe={self.mis_canales}, Neighbors={list(self.canales_vecinos.keys())}")
    
    def init_from_config(self, config):
        self.node_id = config.get("node_id", "A").upper()
        self.vecinos = config.get("topology", {}).get(self.node_id, ["B", "C"])
        
        
        redis_config = config.get("redis", {})
        self.redis_host = redis_config.get("host", "localhost")
        self.redis_port = redis_config.get("port", 6379)
        self.redis_password = redis_config.get("password", "")
        
        
        channels_config = config.get("channels", {})
        if channels_config:
            self.mis_canales = channels_config.get("subscribe", [f"sec20.topologia1.node{self.node_id.lower()}"])
            self.canales_vecinos = channels_config.get("neighbors", {})
        else:
            
            self.mis_canales = [f"sec20.topologia1.node{self.node_id.lower()}"]
            self.canales_vecinos = {vecino: f"sec20.topologia1.node{vecino.lower()}" for vecino in self.vecinos}
        
        
        self.message_format = config.get("message_format", "extended")
        self.node_name_format = config.get("node_name_format", "letters")
    
    def init_default(self):
        self.node_id = "A"
        self.vecinos = ["B", "C"]
        self.redis_host = "localhost"
        self.redis_port = 6379
        self.redis_password = ""
        self.mis_canales = [f"sec20.topologia1.node{self.node_id.lower()}"]
        self.canales_vecinos = {vecino: f"sec20.topologia1.node{vecino.lower()}" for vecino in self.vecinos}
        self.message_format = "extended"
        self.node_name_format = "letters"
    
    def conectar_redis(self):
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password,
                decode_responses=True
            )
            
            
            self.redis_client.ping()
            
            
            self.pubsub = self.redis_client.pubsub()
            
            
            for canal in self.mis_canales:
                self.pubsub.subscribe(canal)
                print(f"[{self.node_id}] Suscrito a canal: {canal}")
            
            return True
            
        except Exception as e:
            print(f"[{self.node_id}] Error conectando a Redis: {e}")
            return False
    
    def crear_packet_lsp(self, nodo_origen, secuencia, vecinos_activos, timestamp):
        headers = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": datetime.now().isoformat(),
            "lsp_origen": nodo_origen,
            "lsp_secuencia": secuencia,
            "lsp_timestamp": timestamp,
            "algorithm": "link_state"
        }
        
        payload = {
            "nodo_origen": nodo_origen,
            "secuencia": secuencia,
            "vecinos": list(vecinos_activos),
            "timestamp": timestamp,
            "costo_enlaces": {vecino: 1 for vecino in vecinos_activos}
        }
        
        return {
            "proto": "enhanced_lsr",
            "type": "lsp",
            "from": self.get_node_name(),
            "to": "broadcast",
            "ttl": 15,
            "headers": headers,
            "payload": payload
        }
    
    def crear_packet_hello(self):
        return {
            "proto": "enhanced_lsr",
            "type": "hello",
            "from": self.get_node_name(),
            "to": "broadcast",
            "ttl": 1,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "algorithm": "link_state"
            },
            "payload": {
                "vecinos_anunciados": self.vecinos,
                "estado": "activo"
            }
        }
    
    def crear_packet_datos(self, destino, contenido):
        return {
            "proto": "enhanced_lsr",
            "type": "message",
            "from": self.get_node_name(),
            "to": destino,
            "ttl": 15,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "algorithm": "link_state"
            },
            "payload": contenido
        }
    
    def get_node_name(self):
        if self.node_name_format == "letters":
            return self.node_id.upper()
        elif self.node_name_format == "email":
            return f"{self.node_id.lower()}@example.com"
        else:
            return f"sec20.topologia1.{self.node_id}"
    
    def enviar_broadcast(self, packet):
        if not self.redis_client:
            print(f"[{self.node_id}] Error: No hay conexión Redis")
            return 0
        
        enviados = 0
        packet_json = json.dumps(packet, ensure_ascii=False)
        
        for vecino, canal in self.canales_vecinos.items():
            try:
                self.redis_client.publish(canal, packet_json)
                enviados += 1
            except Exception as e:
                print(f"[{self.node_id}] Error enviando a {canal}: {e}")
        
        print(f"[{self.node_id}] Broadcast enviado a {enviados}/{len(self.canales_vecinos)} canales")
        return enviados
    
    def enviar_a_vecino(self, vecino, packet):
        if vecino not in self.canales_vecinos:
            print(f"[{self.node_id}] Error: Canal para {vecino} no encontrado")
            return False
        
        canal = self.canales_vecinos[vecino]
        
        try:
            packet_json = json.dumps(packet, ensure_ascii=False)
            self.redis_client.publish(canal, packet_json)
            print(f"[{self.node_id}] Enviado a {vecino} via {canal}")
            return True
        except Exception as e:
            print(f"[{self.node_id}] Error enviando a {vecino}: {e}")
            return False
    
    def generar_lsp_propio(self):
        with self.lock:
            self.secuencia_lsp += 1
            timestamp = time.time()
            
            
            self.lsdb[self.node_id] = {
                'secuencia': self.secuencia_lsp,
                'vecinos': list(self.vecinos_activos),
                'timestamp': timestamp,
                'costo_enlaces': {vecino: 1 for vecino in self.vecinos_activos}
            }
            
            print(f"[{self.node_id}] LSP generado (seq: {self.secuencia_lsp}, vecinos_activos: {len(self.vecinos_activos)})")
    
    def procesar_hello(self, packet):
        origen = packet.get("from", "")
        payload = packet.get("payload", {})
        
        print(f"[{self.node_id}] HELLO recibido de {origen}")
        
        
        if origen in self.vecinos:
            with self.lock:
                self.vecinos_activos.add(origen)
                print(f"[{self.node_id}] Vecino {origen} marcado como activo")
            
            
            self.generar_lsp_propio()
            lsp_info = self.lsdb.get(self.node_id)
            if lsp_info:
                lsp_packet = self.crear_packet_lsp(
                    self.node_id,
                    lsp_info['secuencia'],
                    self.vecinos_activos,
                    lsp_info['timestamp']
                )
                self.enviar_broadcast(lsp_packet)
    
    def procesar_lsp(self, packet):
        payload = packet.get("payload", {})
        nodo_origen = payload.get("nodo_origen", packet.get("from"))
        secuencia = payload.get("secuencia", 1)
        vecinos = payload.get("vecinos", [])
        timestamp = payload.get("timestamp", time.time())
        costo_enlaces = payload.get("costo_enlaces", {})
        
        print(f"[{self.node_id}] LSP recibido de {nodo_origen} (seq: {secuencia}, vecinos: {len(vecinos)})")
        
        with self.lock:
            
            lsp_nuevo = (nodo_origen not in self.lsdb or 
                        secuencia > self.lsdb[nodo_origen]['secuencia'] or
                        (secuencia == self.lsdb[nodo_origen]['secuencia'] and 
                         timestamp > self.lsdb[nodo_origen]['timestamp']))
            
            if lsp_nuevo:
                
                self.lsdb[nodo_origen] = {
                    'secuencia': secuencia,
                    'vecinos': vecinos,
                    'timestamp': timestamp,
                    'costo_enlaces': costo_enlaces
                }
                
                print(f"[{self.node_id}] LSDB actualizada con LSP de {nodo_origen}")
                
                
                self.calcular_dijkstra()
                
                
                if packet.get("ttl", 0) > 1:
                    packet_copy = packet.copy()
                    packet_copy["ttl"] = packet["ttl"] - 1
                    packet_copy["from"] = self.get_node_name()  
                    
                    self.enviar_broadcast(packet_copy)
                    print(f"[{self.node_id}] LSP de {nodo_origen} reenviado")
                
                return True
            else:
                print(f"[{self.node_id}] LSP de {nodo_origen} ignorado (información antigua)")
                return False
    
    def calcular_dijkstra(self):
        
        grafo = defaultdict(dict)
        
        
        for vecino in self.vecinos_activos:
            grafo[self.node_id][vecino] = 1
        
        
        for nodo, info in self.lsdb.items():
            costo_enlaces = info.get('costo_enlaces', {})
            for vecino, costo in costo_enlaces.items():
                grafo[nodo][vecino] = costo
        
        if not grafo:
            print(f"[{self.node_id}] Grafo vacío, no se puede calcular rutas")
            return
        
        
        todos_nodos = set()
        for nodo in grafo:
            todos_nodos.add(nodo)
            todos_nodos.update(grafo[nodo].keys())
        
        distancias = {nodo: float('inf') for nodo in todos_nodos}
        distancias[self.node_id] = 0
        predecesores = {nodo: None for nodo in todos_nodos}
        visitados = set()
        
        cola = [(0, self.node_id)]
        
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
            if destino != self.node_id and dist != float('inf'):
                
                nodo_temp = destino
                ruta = []
                
                while nodo_temp is not None:
                    ruta.append(nodo_temp)
                    nodo_temp = predecesores[nodo_temp]
                
                ruta.reverse()
                
                if len(ruta) > 1:
                    siguiente_salto = ruta[1]
                    nueva_tabla[destino] = {
                        'next_hop': siguiente_salto,
                        'distance': int(dist),
                        'ruta': ruta
                    }
        
        self.tabla_enrutamiento = nueva_tabla
        self.mostrar_tabla_enrutamiento()
    
    def mostrar_tabla_enrutamiento(self):
        if not self.tabla_enrutamiento:
            print(f"[{self.node_id}] Tabla de enrutamiento vacía")
            return
        
        print(f"\n[{self.node_id}] TABLA DE ENRUTAMIENTO LSR:")
        print("-" * 70)
        print("Destino | Siguiente Salto | Distancia | Ruta Completa")
        print("-" * 70)
        
        for destino, info in sorted(self.tabla_enrutamiento.items()):
            ruta_str = " -> ".join(info['ruta'])
            print(f"{destino:^7} | {info['next_hop']:^14} | {info['distance']:^9} | {ruta_str}")
        
        print("-" * 70)
        print(f"Nodos conocidos: {len(self.lsdb)} | Rutas disponibles: {len(self.tabla_enrutamiento)}")
        print()
    
    def procesar_mensaje_datos(self, packet):
        origen = packet.get("from", "")
        destino = packet.get("to", "")
        contenido = packet.get("payload", "")
        ttl = packet.get("ttl", 0)
        
        if destino == self.get_node_name():
            print(f"[{self.node_id}] MENSAJE RECIBIDO de {origen}: '{contenido}'")
            return True
        elif ttl > 1:
            
            return self.reenviar_mensaje(destino, packet)
        else:
            print(f"[{self.node_id}] TTL agotado para mensaje de {origen} a {destino}")
            return False
    
    def reenviar_mensaje(self, destino, packet):
        if destino not in self.tabla_enrutamiento:
            print(f"[{self.node_id}] No hay ruta conocida a {destino}")
            return False
        
        info_ruta = self.tabla_enrutamiento[destino]
        siguiente_salto = info_ruta['next_hop']
        
        
        packet["ttl"] = packet["ttl"] - 1
        
        
        exito = self.enviar_a_vecino(siguiente_salto, packet)
        
        if exito:
            print(f"[{self.node_id}] Mensaje reenviado a {destino} via {siguiente_salto}")
            print(f"[{self.node_id}] Ruta: {' -> '.join(info_ruta['ruta'])}")
        
        return exito
    
    def procesar_mensaje_recibido(self, mensaje_json):
        try:
            packet = json.loads(mensaje_json)
            
            tipo = packet.get("type", "")
            origen = packet.get("from", "")
            msg_id = packet.get("headers", {}).get("id")
            
            
            if msg_id and msg_id in self.mensajes_procesados:
                return
            if msg_id:
                self.mensajes_procesados.add(msg_id)
            
            
            if origen == self.get_node_name():
                return
            
            print(f"[{self.node_id}] Procesando: {tipo} de {origen}")
            
            
            if tipo == "hello":
                self.procesar_hello(packet)
            elif tipo == "lsp":
                self.procesar_lsp(packet)
            elif tipo == "message":
                self.procesar_mensaje_datos(packet)
            else:
                print(f"[{self.node_id}] Tipo de mensaje desconocido: {tipo}")
        
        except json.JSONDecodeError as e:
            print(f"[{self.node_id}] Error decodificando JSON: {e}")
        except Exception as e:
            print(f"[{self.node_id}] Error procesando mensaje: {e}")
    
    def escuchar_mensajes(self):
        try:
            print(f"[{self.node_id}] Iniciando listener de Redis...")
            
            for mensaje in self.pubsub.listen():
                if not self.activo:
                    break
                
                if mensaje['type'] == 'message':
                    self.procesar_mensaje_recibido(mensaje['data'])
                elif mensaje['type'] == 'subscribe':
                    canal = mensaje.get('channel', 'unknown')
                    print(f"[{self.node_id}] Confirmación de suscripción a: {canal}")
        
        except Exception as e:
            print(f"[{self.node_id}] Error en listener: {e}")
        finally:
            print(f"[{self.node_id}] Listener finalizado")
    
    def envio_periodico_hello(self):
        while self.activo:
            time.sleep(10)  
            if self.activo:
                hello_packet = self.crear_packet_hello()
                self.enviar_broadcast(hello_packet)
                print(f"[{self.node_id}] Hello enviado")
    
    def envio_periodico_lsp(self):
        while self.activo:
            time.sleep(30)  
            if self.activo:
                self.generar_lsp_propio()
                lsp_info = self.lsdb.get(self.node_id)
                if lsp_info:
                    lsp_packet = self.crear_packet_lsp(
                        self.node_id,
                        lsp_info['secuencia'],
                        self.vecinos_activos,
                        lsp_info['timestamp']
                    )
                    self.enviar_broadcast(lsp_packet)
                    print(f"[{self.node_id}] LSP periódico enviado")
    
    def enviar_mensaje_prueba(self):
        if self.node_id.upper() == "A":
            time.sleep(15)  
            
            
            destinos_posibles = ["D", "C", "B"]
            destino = None
            
            for posible_destino in destinos_posibles:
                if posible_destino in self.tabla_enrutamiento:
                    destino = posible_destino
                    break
            
            if destino:
                mensaje_packet = self.crear_packet_datos(
                    destino,
                    f"¡Mensaje de prueba desde {self.node_id} usando Enhanced LSR! - {datetime.now().strftime('%H:%M:%S')}"
                )
                
                print(f"[{self.node_id}] Enviando mensaje de prueba a {destino}")
                self.reenviar_mensaje(destino, mensaje_packet)
            else:
                print(f"[{self.node_id}] No hay destinos disponibles para mensaje de prueba")
    
    def iniciar(self):
        print(f"[{self.node_id}] Iniciando Enhanced LSR Node...")
        
        
        if not self.conectar_redis():
            print(f"[{self.node_id}] Error: No se pudo conectar a Redis")
            return
        
        
        self.vecinos_activos = set(self.vecinos)
        
        
        self.generar_lsp_propio()
        
        
        hilo_listener = threading.Thread(target=self.escuchar_mensajes, daemon=True)
        hilo_listener.start()
        
        hilo_hello = threading.Thread(target=self.envio_periodico_hello, daemon=True)
        hilo_hello.start()
        
        hilo_lsp = threading.Thread(target=self.envio_periodico_lsp, daemon=True)
        hilo_lsp.start()
        
        
        time.sleep(2)
        
        
        hello_packet = self.crear_packet_hello()
        self.enviar_broadcast(hello_packet)
        
        
        lsp_info = self.lsdb.get(self.node_id)
        if lsp_info:
            lsp_packet = self.crear_packet_lsp(
                self.node_id,
                lsp_info['secuencia'],
                self.vecinos_activos,
                lsp_info['timestamp']
            )
            self.enviar_broadcast(lsp_packet)
        
        
        threading.Thread(target=self.enviar_mensaje_prueba, daemon=True).start()
        
        print(f"[{self.node_id}] Enhanced LSR Node iniciado exitosamente")
        print(f"[{self.node_id}] Vecinos activos: {self.vecinos_activos}")
        
        
        try:
            while self.activo:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.node_id}] Deteniendo nodo...")
            self.activo = False
        finally:
            self.cleanup()
    
    def cleanup(self):
        self.activo = False
        
        if self.pubsub:
            try:
                self.pubsub.close()
            except:
                pass
        
        if self.redis_client:
            try:
                self.redis_client.close()
            except:
                pass
        
        print(f"[{self.node_id}] Recursos limpiados")

def main():
    import sys
    
    if len(sys.argv) != 2:
        sys.exit(1)
    
    config_file = sys.argv[1]
    
    try:
        nodo = EnhancedRedisLSRNode(config_file)
        nodo.iniciar()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()