import redis
import json
import threading
import time
import uuid
from datetime import datetime
from abc import ABC, abstractmethod

class RedisBaseNode(ABC):
    
    def __init__(self, numero_grupo, email_id="us@.com", topologia=1, seccion=20, prueba=""):
        self.numero_grupo = numero_grupo
        self.topologia = topologia
        self.seccion = seccion
        self.prueba = prueba
        
        self.node_id = email_id
        
        if prueba:
            self.channel = f"sec{seccion}.topologia{topologia}.nodo{numero_grupo}.{prueba}"
        else:
            self.channel = f"sec{seccion}.topologia{topologia}.nodo{numero_grupo}"
        
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        
        self.activo = True
        self.mensajes_procesados = set()
        
        self.pubsub.subscribe(self.channel)
        
        print(f"[{self.node_id}] Nodo inicializado")
        print(f"[{self.node_id}] Canal: {self.channel}")
    
    def crear_mensaje_hello(self, vecinos):
        return {
            "proto": "lsr",
            "type": "hello", 
            "from": self.node_id,
            "to": "broadcast",
            "ttl": 5,
            "headers": [chr(65 + self.numero_grupo - 1)],  
            "payload": ""
        }
    
    def crear_mensaje_info(self, tabla_enrutamiento):
        return {
            "proto": "lsr",
            "type": "info",
            "from": self.node_id,
            "to": "broadcast", 
            "ttl": 5,
            "headers": [chr(65 + self.numero_grupo - 1)],
            "payload": tabla_enrutamiento
        }
    
    def crear_mensaje_message(self, destino_email, contenido):
        return {
            "proto": "lsr", 
            "type": "message",
            "from": self.node_id,
            "to": destino_email,
            "ttl": 5,
            "headers": [chr(65 + self.numero_grupo - 1)],
            "payload": contenido
        }
    
    def actualizar_headers(self, mensaje):
        headers = mensaje.get("headers", [])
        mi_letra = chr(65 + self.numero_grupo - 1)
        
        if mi_letra in headers:
            return None  
        
        if len(headers) >= 3:
            headers = headers[1:]  
        
        headers.append(mi_letra)  
        mensaje["headers"] = headers
        
        return mensaje
    
    def enviar_mensaje(self, mensaje, canal_destino=None):
        try:
            if canal_destino is None:
                return self.enviar_broadcast(mensaje)
            else:
                mensaje_json = json.dumps(mensaje, ensure_ascii=False)
                self.redis_client.publish(canal_destino, mensaje_json)
                print(f"[{self.node_id}] Mensaje enviado a {canal_destino}")
                return True
        except Exception as e:
            print(f"[{self.node_id}] Error enviando mensaje: {e}")
            return False
    
    @abstractmethod
    def enviar_broadcast(self, mensaje):
        pass
    
    @abstractmethod
    def procesar_mensaje_hello(self, mensaje):
        pass
    
    @abstractmethod 
    def procesar_mensaje_info(self, mensaje):
        pass
    
    @abstractmethod
    def procesar_mensaje_message(self, mensaje):
        pass
    
    def procesar_mensaje_recibido(self, mensaje_json):
        try:
            mensaje = json.loads(mensaje_json)
            
            tipo = mensaje.get("type", "")
            origen = mensaje.get("from", "")
            headers = mensaje.get("headers", [])
            ttl = mensaje.get("ttl", 0)
            
            mensaje_id = f"{origen}_{tipo}_{hash(str(mensaje))}"
            
            if mensaje_id in self.mensajes_procesados:
                return  
            
            self.mensajes_procesados.add(mensaje_id)
            
            if origen == self.node_id:
                return
            
            print(f"[{self.node_id}] Recibido {tipo} de {origen}")
            
            if tipo == "hello":
                self.procesar_mensaje_hello(mensaje)
            elif tipo == "info":
                self.procesar_mensaje_info(mensaje)
            elif tipo == "message":
                self.procesar_mensaje_message(mensaje)
            else:
                print(f"[{self.node_id}] Tipo de mensaje desconocido: {tipo}")
                
        except Exception as e:
            print(f"[{self.node_id}] Error procesando mensaje: {e}")
    
    def escuchar_mensajes(self):
        try:
            for mensaje in self.pubsub.listen():
                if not self.activo:
                    break
                    
                if mensaje['type'] == 'message':
                    self.procesar_mensaje_recibido(mensaje['data'])
                    
        except Exception as e:
            print(f"[{self.node_id}] Error en listener: {e}")
        finally:
            self.pubsub.close()
    
    def iniciar(self):
        print(f"[{self.node_id}] Iniciando nodo...")
        
        hilo_listener = threading.Thread(target=self.escuchar_mensajes, daemon=True)
        hilo_listener.start()
        
        time.sleep(1)

        mensaje_hello = self.crear_mensaje_hello([])
        self.enviar_broadcast(mensaje_hello)
        self.inicializacion_algoritmo()
        
        try:
            while self.activo:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.node_id}] Deteniendo nodo...")
            self.activo = False
    
    @abstractmethod
    def inicializacion_algoritmo(self):
        pass
    
    def obtener_canal_nodo(self, numero_nodo, prueba=""):
        if prueba:
            return f"sec{self.seccion}.topologia{self.topologia}.nodo{numero_nodo}.{prueba}"
        else:
            return f"sec{self.seccion}.topologia{self.topologia}.nodo{numero_nodo}"
    
    def numero_a_email(self, numero_nodo):
        return f"nodo{numero_nodo}@.com"
    
    def email_a_numero(self, email):
        try:
            if "@" in email:
                local = email.split("@")[0]
                if "nodo" in local:
                    return int(local.replace("nodo", ""))
            return None
        except:
            return None