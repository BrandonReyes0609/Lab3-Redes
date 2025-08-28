import json
import time
import threading
import heapq
from collections import defaultdict
from redis_base_node import RedisBaseNode

class RedisLSRNode(RedisBaseNode):
    
    def __init__(self, numero_grupo, vecinos_config, email_id="us@.com", topologia=1, seccion=20, prueba=""):
        super().__init__(numero_grupo, email_id, topologia, seccion, prueba)
        
        self.vecinos_numeros = vecinos_config
        self.vecinos_emails = {num: f"nodo{num}@.com" for num in vecinos_config}
        self.vecinos_canales = {num: self.obtener_canal_nodo(num, prueba) for num in vecinos_config}
        
        self.lsdb = {}  
        self.tabla_enrutamiento = {}
        self.secuencia_lsp = 0
        
        self.email_a_letra = {}
        self.letra_a_email = {}
        
        self.lock = threading.Lock()
        
        print(f"[{self.node_id}] LSR Node inicializado")
        print(f"[{self.node_id}] Vecinos: {list(self.vecinos_emails.values())}")
        print(f"[{self.node_id}] Canales: {list(self.vecinos_canales.values())}")
    
    def enviar_broadcast(self, mensaje):
        enviados = 0
        for num, canal in self.vecinos_canales.items():
            if self.enviar_mensaje(mensaje, canal):
                enviados += 1
        
        print(f"[{self.node_id}] Broadcast LSR enviado a {enviados}/{len(self.vecinos_canales)} vecinos")
        return enviados > 0
    
    def procesar_mensaje_hello(self, mensaje):
        origen = mensaje.get("from", "")
        print(f"[{self.node_id}] HELLO recibido de {origen}")
        
        if origen in self.vecinos_emails.values():
            self.enviar_lsp_propio()
    
    def procesar_mensaje_info(self, mensaje):
        origen = mensaje.get("from", "")
        payload = mensaje.get("payload", {})
        ttl = mensaje.get("ttl", 0)
        
        print(f"[{self.node_id}] INFO recibido de {origen}")
        
        with self.lock:
            timestamp = time.time()
            
            vecinos_procesados = {}
            for letra, distancia in payload.items():
                if letra in self.letra_a_email:
                    email = self.letra_a_email[letra]
                    vecinos_procesados[email] = distancia
                else:
                    vecinos_procesados[letra] = distancia
            
            vecinos = []
            for destino, distancia in vecinos_procesados.items():
                if distancia == 1:
                    vecinos.append(destino)
            
            self.lsdb[origen] = {
                'vecinos': vecinos,
                'timestamp': timestamp,
                'distancias': vecinos_procesados
            }
            
            print(f"[{self.node_id}] LSDB actualizada con info de {origen}")
            
            self.calcular_dijkstra()
            
            if ttl > 1 and origen != self.node_id:
                mensaje_actualizado = self.actualizar_headers(mensaje.copy())
                if mensaje_actualizado:
                    mensaje_actualizado["ttl"] = ttl - 1
                    self.reenviar_info(mensaje_actualizado, origen)
    
    def procesar_mensaje_message(self, mensaje):
        origen = mensaje.get("from", "")
        destino = mensaje.get("to", "")
        payload = mensaje.get("payload", "")
        ttl = mensaje.get("ttl", 0)
        
        if destino == self.node_id:
            print(f"[{self.node_id}] MENSAJE RECIBIDO de {origen}: '{payload}'")
        elif ttl > 1:
            if destino in self.tabla_enrutamiento:
                siguiente_email = self.tabla_enrutamiento[destino]['next_hop']
                numero_siguiente = self.email_a_numero(siguiente_email)
                if numero_siguiente:
                    siguiente_canal = self.obtener_canal_nodo(numero_siguiente, self.prueba)
                    
                    mensaje_actualizado = self.actualizar_headers(mensaje.copy())
                    if mensaje_actualizado:
                        mensaje_actualizado["ttl"] = ttl - 1
                        
                        print(f"[{self.node_id}] Reenviando mensaje a {destino} via {siguiente_canal}")
                        self.enviar_mensaje(mensaje_actualizado, siguiente_canal)
                else:
                    print(f"[{self.node_id}] Error: no se pudo resolver siguiente salto")
            else:
                print(f"[{self.node_id}] No hay ruta conocida a {destino}")
        else:
            print(f"[{self.node_id}] TTL agotado, mensaje descartado")
    
    def reenviar_info(self, mensaje, origen):
        for num, canal in self.vecinos_canales.items():
            vecino_email = self.vecinos_emails[num]
            if vecino_email != origen: 
                self.enviar_mensaje(mensaje, canal)
        
        print(f"[{self.node_id}] INFO reenviado por LSR")
    
    def calcular_dijkstra(self):
        if not self.lsdb:
            return
        
        grafo = defaultdict(dict)
        
        for num, email in self.vecinos_emails.items():
            grafo[self.node_id][email] = 1
        
        for nodo_email, info in self.lsdb.items():
            for vecino_email in info.get('vecinos', []):
                grafo[nodo_email][vecino_email] = 1
        
        if not grafo:
            return
        
        todos_nodos = set()
        for nodo in grafo:
            todos_nodos.add(nodo)
            for vecino in grafo[nodo]:
                todos_nodos.add(vecino)
        
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
                while predecesores[nodo_temp] != self.node_id and predecesores[nodo_temp] is not None:
                    nodo_temp = predecesores[nodo_temp]
                
                if predecesores[nodo_temp] == self.node_id:
                    nueva_tabla[destino] = {
                        'next_hop': nodo_temp,
                        'distance': int(dist)
                    }
        
        self.tabla_enrutamiento = nueva_tabla
        self.mostrar_tabla_enrutamiento()
    
    def enviar_lsp_propio(self):
        self.secuencia_lsp += 1
        
        payload = {}
        for i, num in enumerate(self.vecinos_numeros):
            letra = chr(65 + num - 1)  
            payload[letra] = 1
        
        mensaje_info = self.crear_mensaje_info(payload)
        self.enviar_broadcast(mensaje_info)
        
        print(f"[{self.node_id}] LSP propio enviado (seq: {self.secuencia_lsp})")
    
    def mostrar_tabla_enrutamiento(self):
        if not self.tabla_enrutamiento:
            print(f"[{self.node_id}] Tabla de enrutamiento vacía")
            return
        
        print(f"\n[{self.node_id}] TABLA DE ENRUTAMIENTO LSR:")
        print("-" * 50)
        print("Destino Email | Siguiente Salto | Distancia")
        print("-" * 50)
        
        for destino, info in sorted(self.tabla_enrutamiento.items()):
            print(f"{destino:^13} | {info['next_hop']:^14} | {info['distance']:^9}")
        
        print("-" * 50)
        print()
    
    def envio_periodico_lsp(self):
        while self.activo:
            time.sleep(30)
            if self.activo:
                print(f"[{self.node_id}] Enviando LSP periódico")
                self.enviar_lsp_propio()
    
    def inicializacion_algoritmo(self):
        hilo_lsp = threading.Thread(target=self.envio_periodico_lsp, daemon=True)
        hilo_lsp.start()
        
        time.sleep(3)
        self.enviar_lsp_propio()
        
        if self.numero_grupo == 1:
            threading.Thread(target=self.enviar_mensaje_prueba, daemon=True).start()
    
    def enviar_mensaje_prueba(self):
        time.sleep(15)  
        
        if self.tabla_enrutamiento:
            destino_email = list(self.tabla_enrutamiento.keys())[0]
            
            mensaje = self.crear_mensaje_message(
                destino_email,
                f"¡Mensaje de prueba desde {self.node_id} usando LSR! - {time.strftime('%H:%M:%S')}"
            )
            
            print(f"[{self.node_id}] Enviando mensaje de prueba a {destino_email}")
            self.procesar_mensaje_message(mensaje)
        else:
            print(f"[{self.node_id}] No hay destinos disponibles para mensaje de prueba")

def main():
    import sys
    
    if len(sys.argv) < 3:
        print("Uso: python redis_lsr_node.py <numero_grupo> <vecinos> [email] [prueba]")
        print("Ejemplo: python redis_lsr_node.py 1 2,3 nodo1@.com prueba1")
        sys.exit(1)
    
    numero_grupo = int(sys.argv[1])
    vecinos = list(map(int, sys.argv[2].split(',')))
    email_id = sys.argv[3] if len(sys.argv) > 3 else f"nodo{numero_grupo}@.com"
    prueba = sys.argv[4] if len(sys.argv) > 4 else ""
    
    nodo = RedisLSRNode(numero_grupo, vecinos, email_id, prueba=prueba)
    nodo.iniciar()

if __name__ == "__main__":
    main()