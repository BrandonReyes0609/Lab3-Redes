import json
import time
import threading
from collections import defaultdict
from redis_base_node import RedisBaseNode

class RedisDVRNode(RedisBaseNode):
    
    def __init__(self, numero_grupo, vecinos_config, email_id="us@.com", topologia=1, seccion=20, prueba=""):
        super().__init__(numero_grupo, email_id, topologia, seccion, prueba)
        
        self.vecinos_numeros = vecinos_config
        self.vecinos_emails = {num: f"nodo{num}@.com" for num in vecinos_config}
        self.vecinos_canales = {num: self.obtener_canal_nodo(num, prueba) for num in vecinos_config}
        
        self.tabla_enrutamiento = {}
        
        self.tablas_vecinos = defaultdict(dict)
        
        self.lock = threading.Lock()
        
        self.inicializar_tabla()
        
        print(f"[{self.node_id}] DVR Node inicializado")
        print(f"[{self.node_id}] Vecinos: {list(self.vecinos_emails.values())}")
        print(f"[{self.node_id}] Canales: {list(self.vecinos_canales.values())}")
        self.mostrar_tabla_enrutamiento()
    
    def inicializar_tabla(self):
        with self.lock:
            self.tabla_enrutamiento[self.node_id] = {
                'distance': 0,
                'next_hop': self.node_id
            }
            
            for num, email in self.vecinos_emails.items():
                self.tabla_enrutamiento[email] = {
                    'distance': 1,
                    'next_hop': email
                }
    
    def enviar_broadcast(self, mensaje):
        enviados = 0
        for num, canal in self.vecinos_canales.items():
            if self.enviar_mensaje(mensaje, canal):
                enviados += 1
        
        print(f"[{self.node_id}] Vector DVR enviado a {enviados}/{len(self.vecinos_canales)} vecinos")
        return enviados > 0
    
    def procesar_mensaje_hello(self, mensaje):
        origen = mensaje.get("from", "")
        print(f"[{self.node_id}] HELLO recibido de {origen}")
        
        if origen in self.vecinos_emails.values():
            self.enviar_vector_distancias()
    
    def procesar_mensaje_info(self, mensaje):
        origen = mensaje.get("from", "")
        payload = mensaje.get("payload", {})
        ttl = mensaje.get("ttl", 0)
        
        print(f"[{self.node_id}] Vector recibido de {origen}")
        
        self.actualizar_tabla_con_vector(origen, payload)
    
    def procesar_mensaje_message(self, mensaje):
        origen = mensaje.get("from", "")
        destino = mensaje.get("to", "")
        payload = mensaje.get("payload", "")
        ttl = mensaje.get("ttl", 0)
        
        if destino == self.node_id:
            print(f"[{self.node_id}] MENSAJE RECIBIDO de {origen}: '{payload}'")
        elif ttl > 1:
            with self.lock:
                if destino in self.tabla_enrutamiento:
                    info_ruta = self.tabla_enrutamiento[destino]
                    if info_ruta['distance'] < 16: 
                        siguiente_email = info_ruta['next_hop']
                        numero_siguiente = self.email_a_numero(siguiente_email)
                        if numero_siguiente:
                            siguiente_canal = self.obtener_canal_nodo(numero_siguiente, self.prueba)
                            
                            mensaje_actualizado = self.actualizar_headers(mensaje.copy())
                            if mensaje_actualizado:
                                mensaje_actualizado["ttl"] = ttl - 1
                                
                                print(f"[{self.node_id}] Reenviando mensaje a {destino} via {siguiente_canal} (dist: {info_ruta['distance']})")
                                self.enviar_mensaje(mensaje_actualizado, siguiente_canal)
                        else:
                            print(f"[{self.node_id}] Error: no se pudo resolver siguiente salto")
                    else:
                        print(f"[{self.node_id}] Destino {destino} inalcanzable")
                else:
                    print(f"[{self.node_id}] No hay ruta conocida a {destino}")
        else:
            print(f"[{self.node_id}] TTL agotado, mensaje descartado")
    
    def actualizar_tabla_con_vector(self, vecino_origen, vector_distancias):
        self.tablas_vecinos[vecino_origen] = vector_distancias
        tabla_actualizada = False
        
        with self.lock:
            print(f"[{self.node_id}] Procesando vector de {vecino_origen}")
            
            for letra, distancia_vecino in vector_distancias.items():
                numero_destino = ord(letra) - 64  
                destino_email = f"nodo{numero_destino}@.com"
                
                if destino_email == self.node_id:
                    continue  
                
                distancia_via_vecino = 1 + int(distancia_vecino)
                
                if (destino_email not in self.tabla_enrutamiento or 
                    distancia_via_vecino < self.tabla_enrutamiento[destino_email]['distance']):
                    
                    self.tabla_enrutamiento[destino_email] = {
                        'distance': distancia_via_vecino,
                        'next_hop': vecino_origen
                    }
                    tabla_actualizada = True
                    print(f"[{self.node_id}] Ruta mejorada a {destino_email}: {distancia_via_vecino} via {vecino_origen}")
            
            rutas_a_revisar = []
            for destino, info in self.tabla_enrutamiento.items():
                if info['next_hop'] == vecino_origen and destino != self.node_id:
                    numero_destino = self.email_a_numero(destino)
                    if numero_destino:
                        letra_destino = chr(64 + numero_destino) 
                        if letra_destino not in vector_distancias:
                            info['distance'] = 16  
                            tabla_actualizada = True
                            print(f"[{self.node_id}] Ruta a {destino} ahora inalcanzable")
        
        if tabla_actualizada:
            self.mostrar_tabla_enrutamiento()
            self.enviar_vector_distancias()
    
    def enviar_vector_distancias(self):
        with self.lock:
            payload = {}
            for destino_email, info in self.tabla_enrutamiento.items():
                if info['distance'] < 16:  
                    numero_destino = self.email_a_numero(destino_email)
                    if numero_destino:
                        letra = chr(64 + numero_destino)  
                        payload[letra] = info['distance']
        
        mensaje_info = self.crear_mensaje_info(payload)
        self.enviar_broadcast(mensaje_info)
        
        print(f"[{self.node_id}] Vector de distancias enviado")
    
    def mostrar_tabla_enrutamiento(self):
        print(f"\n[{self.node_id}] TABLA DE ENRUTAMIENTO DVR:")
        print("-" * 55)
        print("Destino Email | Distancia | Siguiente Salto Email")
        print("-" * 55)
        
        with self.lock:
            for destino, info in sorted(self.tabla_enrutamiento.items()):
                distancia = info['distance']
                siguiente = info['next_hop']
                distancia_str = str(distancia) if distancia < 16 else "∞"
                
                print(f"{destino:^13} | {distancia_str:^9} | {siguiente:^19}")
        
        print("-" * 55)
        print()
    
    def envio_periodico_vector(self):
        while self.activo:
            time.sleep(15)
            if self.activo:
                print(f"[{self.node_id}] Enviando vector periódico")
                self.enviar_vector_distancias()
    
    def inicializacion_algoritmo(self):
        hilo_vector = threading.Thread(target=self.envio_periodico_vector, daemon=True)
        hilo_vector.start()
        
        time.sleep(3)
        self.enviar_vector_distancias()
        
        if self.numero_grupo == 1:
            threading.Thread(target=self.enviar_mensaje_prueba, daemon=True).start()
    
    def enviar_mensaje_prueba(self):
        time.sleep(10)  

        with self.lock:
            destinos_validos = [d for d, info in self.tabla_enrutamiento.items() 
                              if info['distance'] < 16 and d != self.node_id]
        
        if destinos_validos:
            destino_email = destinos_validos[0]
            
            mensaje = self.crear_mensaje_message(
                destino_email,
                f"¡Mensaje de prueba desde {self.node_id} usando DVR! - {time.strftime('%H:%M:%S')}"
            )
            
            print(f"[{self.node_id}] Enviando mensaje de prueba a {destino_email}")
            self.procesar_mensaje_message(mensaje)
        else:
            print(f"[{self.node_id}] No hay destinos disponibles para mensaje de prueba")

def main():
    import sys
    
    if len(sys.argv) < 3:
        print("Uso: python redis_dvr_node.py <numero_grupo> <vecinos> [email] [prueba]")
        print("Ejemplo: python redis_dvr_node.py 1 2,3 nodo1@.com prueba1")
        sys.exit(1)
    
    numero_grupo = int(sys.argv[1])
    vecinos = list(map(int, sys.argv[2].split(',')))
    email_id = sys.argv[3] if len(sys.argv) > 3 else f"nodo{numero_grupo}@.com"
    prueba = sys.argv[4] if len(sys.argv) > 4 else ""
    
    nodo = RedisDVRNode(numero_grupo, vecinos, email_id, prueba=prueba)
    nodo.iniciar()

if __name__ == "__main__":
    main()