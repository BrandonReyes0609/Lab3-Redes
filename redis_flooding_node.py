import json
import time
import threading
from redis_base_node import RedisBaseNode

class RedisFloodingNode(RedisBaseNode):
    
    def __init__(self, numero_grupo, vecinos_config, email_id="us@.com", topologia=1, seccion=20, prueba=""):
        super().__init__(numero_grupo, email_id, topologia, seccion, prueba)
        
        self.vecinos_numeros = vecinos_config
        self.vecinos_emails = {num: f"nodo{num}@.com" for num in vecinos_config}
        self.vecinos_canales = {num: self.obtener_canal_nodo(num, prueba) for num in vecinos_config}
        
        print(f"[{self.node_id}] Flooding Node inicializado")
        print(f"[{self.node_id}] Vecinos: {list(self.vecinos_emails.values())}")
        print(f"[{self.node_id}] Canales: {list(self.vecinos_canales.values())}")
    
    def enviar_broadcast(self, mensaje):
        enviados = 0
        for num, canal in self.vecinos_canales.items():
            if self.enviar_mensaje(mensaje, canal):
                enviados += 1
        
        print(f"[{self.node_id}] Flooding a {enviados}/{len(self.vecinos_canales)} vecinos")
        return enviados > 0
    
    def procesar_mensaje_hello(self, mensaje):
        origen = mensaje.get("from", "")
        print(f"[{self.node_id}] HELLO recibido de {origen}")
        
        if origen in self.vecinos_emails.values():
            print(f"[{self.node_id}] Vecino {origen} confirmado")
    
    def procesar_mensaje_info(self, mensaje):
        origen = mensaje.get("from", "")
        ttl = mensaje.get("ttl", 0)
        
        print(f"[{self.node_id}] INFO recibido de {origen}")
        
        if ttl > 1 and origen != self.node_id:
            mensaje_actualizado = self.actualizar_headers(mensaje.copy())
            if mensaje_actualizado:
                mensaje_actualizado["ttl"] = ttl - 1
                self.reenviar_flooding(mensaje_actualizado, origen)
    
    def procesar_mensaje_message(self, mensaje):
        origen = mensaje.get("from", "")
        destino = mensaje.get("to", "")
        payload = mensaje.get("payload", "")
        ttl = mensaje.get("ttl", 0)
        
        if destino == self.node_id:
            print(f"[{self.node_id}] MENSAJE RECIBIDO de {origen}: '{payload}'")
        elif ttl > 1:
            mensaje_actualizado = self.actualizar_headers(mensaje.copy())
            if mensaje_actualizado:
                mensaje_actualizado["ttl"] = ttl - 1
                
                print(f"[{self.node_id}] Reenviando mensaje por flooding")
                self.reenviar_flooding(mensaje_actualizado, origen)
        else:
            print(f"[{self.node_id}] TTL agotado, mensaje descartado")
    
    def reenviar_flooding(self, mensaje, origen):
        enviados = 0
        
        for num, canal in self.vecinos_canales.items():
            vecino_email = self.vecinos_emails[num]
            if vecino_email != origen:  
                if self.enviar_mensaje(mensaje, canal):
                    enviados += 1
        
        print(f"[{self.node_id}] Mensaje reenviado por flooding a {enviados} vecinos")
    
    def inicializacion_algoritmo(self):
        print(f"[{self.node_id}] Algoritmo Flooding inicializado")
        
        if self.numero_grupo == 1:
            threading.Thread(target=self.enviar_mensaje_prueba, daemon=True).start()
    
    def enviar_mensaje_prueba(self):
        time.sleep(5)  

        if self.vecinos_emails:
            destino_email = list(self.vecinos_emails.values())[-1]
        else:
            destino_email = "whatever@.com"
        
        mensaje = self.crear_mensaje_message(
            destino_email,
            f"¡Mensaje de prueba desde {self.node_id} usando Flooding! - {time.strftime('%H:%M:%S')}"
        )
        
        print(f"[{self.node_id}] Enviando mensaje de prueba a {destino_email} por flooding")
        self.procesar_mensaje_message(mensaje)

def main():
    import sys
    
    if len(sys.argv) < 3:
        print("Uso: python redis_flooding_node.py <numero_grupo> <vecinos> [email] [prueba]")
        print("Ejemplo: python redis_flooding_node.py 1 2,3 nodo1@.com prueba1")
        sys.exit(1)
    
    numero_grupo = int(sys.argv[1])
    vecinos = list(map(int, sys.argv[2].split(',')))
    email_id = sys.argv[3] if len(sys.argv) > 3 else f"nodo{numero_grupo}@.com"
    prueba = sys.argv[4] if len(sys.argv) > 4 else ""
    
    nodo = RedisFloodingNode(numero_grupo, vecinos, email_id, prueba=prueba)
    nodo.iniciar()

if __name__ == "__main__":
    main()