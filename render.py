import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import socket
import uuid
import redis
import time
from datetime import datetime
from abc import ABC, abstractmethod


PUERTO_BASE_LOCAL = 5000
TAMANIO_BUFFER = 4096
VALOR_TTL_INICIAL = 5

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

class LocalSocketMode(CommunicationMode):
    
    def __init__(self, nodo_id):
        self.nodo_id = nodo_id
        self.puerto = PUERTO_BASE_LOCAL + (ord(nodo_id.upper()) - ord('A'))
        self.servidor_socket = None
        self.activo = True
        
    def initialize(self):
        return True
    
    def send_message(self, destino, mensaje):
        try:
            puerto_destino = PUERTO_BASE_LOCAL + (ord(destino.upper()) - ord('A'))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("localhost", puerto_destino))
                s.sendall(json.dumps(mensaje).encode('utf-8'))
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
        
        
        if channels_config:
            self.mis_canales = channels_config.get("subscribe", [f"sec20.topologia1.node{nodo_id.lower()}"])
            self.canales_vecinos = channels_config.get("neighbors", {})
        else:
            self.mis_canales = [f"sec20.topologia1.node{nodo_id.lower()}"]
            self.canales_vecinos = {}
        
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
                "proto": "gui_redis",
                "type": mensaje.get("type", "message"),
                "from": self.nodo_id,
                "to": destino,
                "ttl": mensaje.get("ttl", 5),
                "headers": {
                    "id": mensaje.get("headers", {}).get("id", str(uuid.uuid4())[:8]),
                    "timestamp": datetime.now().isoformat(),
                    "channel": canal_destino
                },
                "payload": mensaje.get("payload", "")
            }
            
            
            print(f"[{self.nodo_id}] Enviando a canal {canal_destino}: {mensaje_redis['type']}")
            
            self.redis_client.publish(canal_destino, json.dumps(mensaje_redis))
            return True
        except Exception as e:
            print(f"[{self.nodo_id}] Error enviando a {destino}: {e}")
            return False, str(e)
    
    def start_listening(self, callback):
        def escuchar():
            try:
                print(f"[{self.nodo_id}] Iniciando listener Redis...")
                for mensaje in self.pubsub.listen():
                    if not self.activo:
                        break
                    if mensaje['type'] == 'message':
                        
                        canal = mensaje.get('channel', 'unknown')
                        print(f"[{self.nodo_id}] Mensaje recibido en canal: {canal}")
                        if callback:
                            callback(mensaje['data'])
                    elif mensaje['type'] == 'subscribe':
                        canal = mensaje.get('channel', 'unknown')
                        print(f"[{self.nodo_id}] Suscrito exitosamente a: {canal}")
            except Exception as e:
                print(f"[{self.nodo_id}] Error en listener Redis: {e}")
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
        if self.redis_client:
            try:
                self.redis_client.close()
            except:
                pass

class HybridNetworkGUI:
    def __init__(self):
        self.ventana = tk.Tk()
        self.ventana.title("Router GUI - Modo Híbrido (Local/Redis)")
        self.ventana.geometry("800x700")
        
        
        self.nodo_id = "A"
        self.vecinos = ["B", "C", "D"]
        self.modo_actual = None
        self.communication_mode = None
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
        
        
        self.message_format = "flexible"
        self.node_name_format = "letters"
        
        
        self.topologia_completa = {}
        
        self.crear_interfaz()
    
    def crear_interfaz(self):
        
        main_frame = ttk.Frame(self.ventana, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        
        self.ventana.columnconfigure(0, weight=1)
        self.ventana.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        
        config_frame = ttk.LabelFrame(main_frame, text="Configuración", padding=10)
        config_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,10))
        config_frame.columnconfigure(1, weight=1)
        
        
        ttk.Label(config_frame, text="Modo:").grid(row=0, column=0, sticky="w")
        self.modo_var = tk.StringVar(value="local")
        modo_frame = ttk.Frame(config_frame)
        modo_frame.grid(row=0, column=1, sticky="ew")
        
        ttk.Radiobutton(modo_frame, text="Local (Sockets)", variable=self.modo_var, 
                       value="local", command=self.cambiar_modo).pack(side="left")
        ttk.Radiobutton(modo_frame, text="Redis", variable=self.modo_var, 
                       value="redis", command=self.cambiar_modo).pack(side="left", padx=(20,0))
        
        
        ttk.Label(config_frame, text="ID Nodo:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.nodo_entry = ttk.Entry(config_frame, width=10)
        self.nodo_entry.grid(row=1, column=1, sticky="w", pady=(5,0))
        self.nodo_entry.insert(0, self.nodo_id)
        
        
        ttk.Label(config_frame, text="Vecinos:").grid(row=2, column=0, sticky="w", pady=(5,0))
        self.vecinos_entry = ttk.Entry(config_frame, width=30)
        self.vecinos_entry.grid(row=2, column=1, sticky="ew", pady=(5,0))
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
        botones_config_frame.grid(row=4, column=0, columnspan=2, pady=(10,0))
        
        ttk.Button(botones_config_frame, text="Cargar Config JSON", 
                  command=self.cargar_configuracion).pack(side="left", padx=(0,5))
        ttk.Button(botones_config_frame, text="Guardar Config", 
                  command=self.guardar_configuracion).pack(side="left", padx=(0,5))
        ttk.Button(botones_config_frame, text="Test Redis", 
                  command=self.probar_conectividad_redis).pack(side="left", padx=(0,5))
        ttk.Button(botones_config_frame, text="Conectar", 
                  command=self.conectar, state="normal").pack(side="left", padx=(0,5))
        self.status_label = ttk.Label(botones_config_frame, text="Desconectado", foreground="red")
        self.status_label.pack(side="left", padx=(10,0))
        
        
        mensaje_frame = ttk.LabelFrame(main_frame, text="Enviar Mensaje", padding=10)
        mensaje_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0,10))
        mensaje_frame.columnconfigure(1, weight=1)
        
        ttk.Label(mensaje_frame, text="Destino:").grid(row=0, column=0, sticky="w")
        self.destino_combo = ttk.Combobox(mensaje_frame, values=self.vecinos, width=15)
        self.destino_combo.grid(row=0, column=1, sticky="w")
        
        ttk.Label(mensaje_frame, text="Tipo:").grid(row=0, column=2, sticky="w", padx=(10,5))
        self.tipo_combo = ttk.Combobox(mensaje_frame, values=["message", "echo", "hello", "info"], width=10)
        self.tipo_combo.grid(row=0, column=3, sticky="w")
        self.tipo_combo.set("message")
        
        ttk.Label(mensaje_frame, text="Mensaje:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.mensaje_entry = ttk.Entry(mensaje_frame, width=50)
        self.mensaje_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(5,0))
        self.mensaje_entry.bind("<Return>", lambda e: self.enviar_mensaje())
        
        ttk.Button(mensaje_frame, text="Enviar", command=self.enviar_mensaje).grid(row=1, column=3, pady=(5,0), padx=(5,0))
        
        
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0,10))
        
        ttk.Button(control_frame, text="Ping Vecinos", command=self.ping_vecinos).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Mensaje Personalizado", command=self.enviar_mensaje_personalizado).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Mostrar Estado", command=self.mostrar_estado).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Limpiar Log", command=self.limpiar_log).pack(side="left", padx=(0,5))
        ttk.Button(control_frame, text="Desconectar", command=self.desconectar).pack(side="right")
        
        
        log_frame = ttk.LabelFrame(main_frame, text="Log de Mensajes", padding=5)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0,0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, width=80, height=20, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        
        self.log_text.tag_configure("enviado", foreground="blue")
        self.log_text.tag_configure("recibido", foreground="green")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("sistema", foreground="purple")
        
        
        self.cambiar_modo()
    
    def cambiar_modo(self):
        modo = self.modo_var.get()
        
        if modo == "redis":
            self.redis_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10,0))
            self.redis_frame.columnconfigure(1, weight=1)
            self.redis_frame.columnconfigure(3, weight=1)
        else:
            self.redis_frame.grid_remove()
        
        
        if self.communication_mode:
            self.desconectar()
    
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
                
                
                if 'message_format' in config:
                    self.message_format = config['message_format']
                
                if 'node_name_format' in config:
                    self.node_name_format = config['node_name_format']
                
                
                self.configuracion_redis.update(config.get('redis', {}))
                
                self.log_mensaje("✓ Configuración completa cargada exitosamente", "sistema")
                
                
                resumen = self.generar_resumen_configuracion(config)
                self.log_mensaje(resumen, "sistema")
                
            except Exception as e:
                messagebox.showerror("Error", f"Error cargando configuración: {e}")
                self.log_mensaje(f"✗ Error cargando configuración: {e}", "error")
    
    def generar_resumen_configuracion(self, config):
        resumen = "Configuración cargada:\n"
        resumen += f"  • Nodo: {config.get('node_id', 'N/A')}\n"
        resumen += f"  • Formato mensaje: {config.get('message_format', 'N/A')}\n"
        resumen += f"  • Formato nombre: {config.get('node_name_format', 'N/A')}\n"
        
        if 'redis' in config:
            redis_cfg = config['redis']
            resumen += f"  • Redis: {redis_cfg.get('host', 'localhost')}:{redis_cfg.get('port', 6379)}\n"
        
        if 'channels' in config:
            channels = config['channels']
            if 'subscribe' in channels:
                resumen += f"  • Canales suscritos: {len(channels['subscribe'])}\n"
            if 'neighbors' in channels:
                resumen += f"  • Canales vecinos: {len(channels['neighbors'])}\n"
        
        if 'topology' in config:
            resumen += f"  • Nodos en topología: {len(config['topology'])}\n"
        
        return resumen
    
    def conectar(self):
        try:
            
            self.nodo_id = self.nodo_entry.get().strip().upper()
            vecinos_str = self.vecinos_entry.get().strip()
            self.vecinos = [v.strip().upper() for v in vecinos_str.split(",") if v.strip()]
            
            if not self.nodo_id:
                messagebox.showerror("Error", "ID de nodo requerido")
                return
            
            self.log_mensaje(f"[{self.nodo_id}] Iniciando proceso de conexión...", "sistema")
            
            
            if self.communication_mode:
                self.log_mensaje(f"[{self.nodo_id}] Cerrando conexión anterior...", "sistema")
                self.desconectar()
            
            modo = self.modo_var.get()
            self.log_mensaje(f"[{self.nodo_id}] Modo seleccionado: {modo.upper()}", "sistema")
            
            if modo == "local":
                puerto = PUERTO_BASE_LOCAL + (ord(self.nodo_id) - ord('A'))
                self.log_mensaje(f"[{self.nodo_id}] Configurando modo LOCAL en puerto {puerto}", "sistema")
                
                self.communication_mode = LocalSocketMode(self.nodo_id)
                success = self.communication_mode.initialize()
                if not success:
                    raise Exception("No se pudo inicializar modo local")
                
            elif modo == "redis":
                
                self.configuracion_redis = {
                    'host': self.redis_host_entry.get().strip(),
                    'port': int(self.redis_port_entry.get().strip()),
                    'password': self.redis_pass_entry.get().strip()
                }
                
                self.log_mensaje(f"[{self.nodo_id}] Configurando REDIS: {self.configuracion_redis['host']}:{self.configuracion_redis['port']}", "sistema")
                
                
                channels_config = None
                if self.configuracion_canales.get('subscribe') or self.configuracion_canales.get('neighbors'):
                    channels_config = self.configuracion_canales
                    self.log_mensaje(f"[{self.nodo_id}] Usando configuración de canales desde JSON", "sistema")
                    self.log_mensaje(f"[{self.nodo_id}] Canales subscribe: {self.configuracion_canales.get('subscribe', [])}", "sistema")
                    self.log_mensaje(f"[{self.nodo_id}] Canales neighbors: {list(self.configuracion_canales.get('neighbors', {}).keys())}", "sistema")
                else:
                    
                    channels_config = {
                        'subscribe': [f"sec20.topologia1.node{self.nodo_id.lower()}"],
                        'neighbors': {vecino: f"sec20.topologia1.node{vecino.lower()}" for vecino in self.vecinos}
                    }
                    self.log_mensaje(f"[{self.nodo_id}] Generando canales por defecto", "sistema")
                    for vecino, canal in channels_config['neighbors'].items():
                        self.log_mensaje(f"[{self.nodo_id}] Canal para {vecino}: {canal}", "sistema")
                
                self.communication_mode = RedisMode(self.nodo_id, self.configuracion_redis, channels_config)
                result = self.communication_mode.initialize()
                if isinstance(result, tuple) and not result[0]:
                    raise Exception(result[1])
                
                self.log_mensaje(f"[{self.nodo_id}] Conexión Redis establecida exitosamente", "sistema")
            
            
            self.log_mensaje(f"[{self.nodo_id}] Iniciando listener de mensajes...", "sistema")
            status_msg = self.communication_mode.start_listening(self.procesar_mensaje_recibido)
            
            
            self.destino_combo.config(values=self.vecinos)
            self.status_label.config(text=f"Conectado ({modo})", foreground="green")
            
            
            self.log_mensaje(f"[{self.nodo_id}] ✓ CONECTADO como {self.nodo_id} en modo {modo.upper()}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] Vecinos configurados: {', '.join(self.vecinos)}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] {status_msg}", "sistema")
            
            if modo == "redis":
                if self.configuracion_canales.get('subscribe'):
                    for canal in self.configuracion_canales['subscribe']:
                        self.log_mensaje(f"[{self.nodo_id}] Suscrito a: {canal}", "sistema")
                        
                if self.configuracion_canales.get('neighbors'):
                    self.log_mensaje(f"[{self.nodo_id}] Canales vecinos configurados: {len(self.configuracion_canales['neighbors'])}", "sistema")
                
            self.log_mensaje(f"[{self.nodo_id}] Formato mensaje: {self.message_format}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] Formato nombre: {self.node_name_format}", "sistema")
            self.log_mensaje(f"[{self.nodo_id}] ¡Listo para enviar/recibir mensajes!", "sistema")
            
        except Exception as e:
            messagebox.showerror("Error de Conexión", str(e))
            self.status_label.config(text="Error de conexión", foreground="red")
            self.log_mensaje(f"[{self.nodo_id}] ✗ ERROR DE CONEXIÓN: {e}", "error")
    
    def desconectar(self):
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
        
        
        mensaje = {
            "proto": "hybrid_gui",
            "type": tipo,
            "from": self.nodo_id,
            "to": destino,
            "ttl": VALOR_TTL_INICIAL,
            "headers": {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat()
            },
            "payload": contenido
        }
        
        
        result = self.communication_mode.send_message(destino, mensaje)
        
        if isinstance(result, tuple):
            success, error = result
            if success:
                self.log_mensaje(f"→ Enviado a {destino} ({tipo}): {contenido}", "enviado")
                self.mensaje_entry.delete(0, tk.END)
            else:
                self.log_mensaje(f"✗ Error enviando a {destino}: {error}", "error")
        elif result:
            self.log_mensaje(f"→ Enviado a {destino} ({tipo}): {contenido}", "enviado")
            self.mensaje_entry.delete(0, tk.END)
        else:
            self.log_mensaje(f"✗ Error enviando a {destino}", "error")
    
    def procesar_mensaje_recibido(self, datos):
        try:
            
            self.log_mensaje(f"[RAW] Recibido: {datos[:150]}{'...' if len(datos) > 150 else ''}", "sistema")
            
            paquete = json.loads(datos)
            
            
            origen = paquete.get("from", "desconocido")
            destino = paquete.get("to", "")
            contenido = paquete.get("payload", "")
            tipo = paquete.get("type", "message")
            ttl = paquete.get("ttl", 0)
            proto = paquete.get("proto", "unknown")
            msg_id = paquete.get("headers", {}).get("id")
            
            
            self.log_mensaje(f"[{self.nodo_id}] Paquete recibido: {proto} | {tipo} | {origen} → {destino} | TTL:{ttl}", "recibido")
            
            
            if msg_id and msg_id in self.mensajes_recibidos:
                self.log_mensaje(f"[{self.nodo_id}] Mensaje duplicado ignorado (ID: {msg_id})", "sistema")
                return
            if msg_id:
                self.mensajes_recibidos.add(msg_id)
            
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            if destino == self.nodo_id:
                
                if tipo == "echo":
                    self.log_mensaje(f"[{self.nodo_id}] ECHO RECIBIDO de {origen}", "recibido")
                elif tipo == "hello":
                    self.log_mensaje(f"[{self.nodo_id}] HELLO RECIBIDO de {origen}: {contenido}", "recibido")
                elif tipo == "info" or tipo == "lsp" or tipo == "distance_vector":
                    self.log_mensaje(f"[{self.nodo_id}] INFO RECIBIDO de {origen}: {tipo}", "recibido")
                    
                    if len(str(contenido)) < 200:
                        self.log_mensaje(f"[{self.nodo_id}] Contenido: {contenido}", "recibido")
                elif tipo == "message":
                    self.log_mensaje(f"[{self.nodo_id}] MENSAJE RECIBIDO de {origen}: '{contenido}'", "recibido")
                else:
                    self.log_mensaje(f"[{self.nodo_id}] {tipo.upper()} RECIBIDO de {origen}: {contenido}", "recibido")
            
            elif destino == "broadcast" or destino.lower() == "broadcast":
                
                self.log_mensaje(f"[{self.nodo_id}] BROADCAST de {origen}: {tipo} | {contenido[:50]}{'...' if len(str(contenido)) > 50 else ''}", "recibido")
                
            else:
                
                self.log_mensaje(f"[{self.nodo_id}] TRÁNSITO: {origen} → {destino} | {tipo} | TTL:{ttl}", "sistema")
                if self.modo_var.get() == "local":
                    self.log_mensaje(f"[{self.nodo_id}] Contenido en tránsito: {contenido[:100]}{'...' if len(str(contenido)) > 100 else ''}", "sistema")
            
            
            headers = paquete.get("headers", {})
            if isinstance(headers, dict):
                headers_info = []
                for key, value in headers.items():
                    if key not in ['id', 'timestamp']:  
                        headers_info.append(f"{key}:{value}")
                if headers_info:
                    self.log_mensaje(f"[{self.nodo_id}] Headers: {', '.join(headers_info)}", "sistema")
            
        except json.JSONDecodeError as e:
            self.log_mensaje(f"[{self.nodo_id}] ERROR JSON: {datos[:100]}... | {e}", "error")
        except Exception as e:
            self.log_mensaje(f"[{self.nodo_id}] ERROR procesando mensaje: {e}", "error")
            
            self.log_mensaje(f"[DEBUG] Datos problemáticos: {datos[:200]}{'...' if len(datos) > 200 else ''}", "error")
    
    def ping_vecinos(self):
        if not self.communication_mode:
            messagebox.showwarning("Advertencia", "No conectado")
            return
        
        for vecino in self.vecinos:
            mensaje = {
                "proto": "hybrid_gui",
                "type": "hello",
                "from": self.nodo_id,
                "to": vecino,
                "ttl": 1,
                "headers": {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().isoformat()
                },
                "payload": f"Hello desde {self.nodo_id}"
            }
            
            result = self.communication_mode.send_message(vecino, mensaje)
            if isinstance(result, tuple) and not result[0]:
                self.log_mensaje(f"✗ Error ping a {vecino}: {result[1]}", "error")
        
        self.log_mensaje(f"Ping enviado a {len(self.vecinos)} vecinos", "sistema")
    
    def mostrar_estado(self):
        modo = self.modo_var.get()
        estado = f"Estado del Nodo: {self.nodo_id}\n"
        estado += f"Modo: {modo.upper()}\n"
        estado += f"Vecinos: {', '.join(self.vecinos)}\n"
        estado += f"Mensajes recibidos: {len(self.mensajes_recibidos)}\n"
        estado += f"Formato mensaje: {self.message_format}\n"
        estado += f"Formato nombre: {self.node_name_format}\n"
        
        if modo == "redis":
            estado += f"\nConfiguración Redis:\n"
            estado += f"  Host: {self.configuracion_redis['host']}\n"
            estado += f"  Puerto: {self.configuracion_redis['port']}\n"
            estado += f"  Password: {'*' * len(self.configuracion_redis.get('password', ''))}\n"
            
            if self.configuracion_canales.get('subscribe'):
                estado += f"\nCanales suscritos: {len(self.configuracion_canales['subscribe'])}\n"
                for canal in self.configuracion_canales['subscribe']:
                    estado += f"  • {canal}\n"
            
            if self.configuracion_canales.get('neighbors'):
                estado += f"\nCanales vecinos: {len(self.configuracion_canales['neighbors'])}\n"
                for vecino, canal in self.configuracion_canales['neighbors'].items():
                    estado += f"  • {vecino} → {canal}\n"
                    
        elif modo == "local":
            puerto = PUERTO_BASE_LOCAL + (ord(self.nodo_id) - ord('A'))
            estado += f"\nPuerto Local: {puerto}\n"
        
        if self.topologia_completa:
            estado += f"\nTopología completa:\n"
            for nodo, vecinos_nodo in self.topologia_completa.items():
                estado += f"  • {nodo}: {', '.join(vecinos_nodo)}\n"
        
        self.log_mensaje(estado, "sistema")
    
    def guardar_configuracion(self):
        archivo = filedialog.asksaveasfilename(
            title="Guardar configuración",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            defaultextension=".json"
        )
        
        if archivo:
            try:
                config = {
                    "node_id": self.nodo_id,
                    "message_format": self.message_format,
                    "node_name_format": self.node_name_format,
                    "redis": self.configuracion_redis,
                    "channels": self.configuracion_canales,
                    "topology": self.topologia_completa if self.topologia_completa else {
                        self.nodo_id: self.vecinos
                    }
                }
                
                with open(archivo, 'w') as f:
                    json.dump(config, f, indent=2)
                
                self.log_mensaje(f"✓ Configuración guardada en: {archivo}", "sistema")
                
            except Exception as e:
                messagebox.showerror("Error", f"Error guardando configuración: {e}")
                self.log_mensaje(f"✗ Error guardando configuración: {e}", "error")
    
    def probar_conectividad_redis(self):
        if not self.configuracion_redis:
            messagebox.showwarning("Advertencia", "No hay configuración de Redis cargada")
            return
            
        try:
            test_client = redis.Redis(
                host=self.configuracion_redis['host'],
                port=self.configuracion_redis['port'],
                password=self.configuracion_redis['password'],
                decode_responses=True,
                socket_timeout=5
            )
            
            test_client.ping()
            test_client.close()
            
            self.log_mensaje("✓ Conectividad Redis OK", "sistema")
            messagebox.showinfo("Conectividad", "Conexión a Redis exitosa")
            
        except Exception as e:
            self.log_mensaje(f"✗ Error conectividad Redis: {e}", "error")
            messagebox.showerror("Error", f"No se pudo conectar a Redis: {e}")
    
    def enviar_mensaje_personalizado(self):
        if not self.communication_mode:
            messagebox.showwarning("Advertencia", "No conectado")
            return
        
        
        ventana_msg = tk.Toplevel(self.ventana)
        ventana_msg.title("Mensaje Personalizado")
        ventana_msg.geometry("500x400")
        ventana_msg.transient(self.ventana)
        
        frame = ttk.Frame(ventana_msg, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        ventana_msg.columnconfigure(0, weight=1)
        ventana_msg.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        
        
        ttk.Label(frame, text="Destino:").grid(row=0, column=0, sticky="w")
        destino_entry = ttk.Entry(frame, width=20)
        destino_entry.grid(row=0, column=1, sticky="ew", pady=(0,5))
        
        ttk.Label(frame, text="Tipo:").grid(row=1, column=0, sticky="w")
        tipo_entry = ttk.Entry(frame, width=20)
        tipo_entry.grid(row=1, column=1, sticky="ew", pady=(0,5))
        tipo_entry.insert(0, "message")
        
        ttk.Label(frame, text="TTL:").grid(row=2, column=0, sticky="w")
        ttl_entry = ttk.Entry(frame, width=20)
        ttl_entry.grid(row=2, column=1, sticky="ew", pady=(0,5))
        ttl_entry.insert(0, "5")
        
        ttk.Label(frame, text="Headers (JSON):").grid(row=3, column=0, sticky="nw")
        headers_text = scrolledtext.ScrolledText(frame, width=50, height=5)
        headers_text.grid(row=3, column=1, sticky="ew", pady=(0,5))
        headers_text.insert(tk.END, '{"custom": "value"}')
        
        ttk.Label(frame, text="Payload:").grid(row=4, column=0, sticky="nw")
        payload_text = scrolledtext.ScrolledText(frame, width=50, height=8)
        payload_text.grid(row=4, column=1, sticky="ew", pady=(0,10))
        frame.rowconfigure(4, weight=1)
        
        def enviar_personalizado():
            try:
                headers_json = json.loads(headers_text.get(1.0, tk.END))
                headers_json.update({
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().isoformat()
                })
                
                mensaje = {
                    "proto": "hybrid_gui_custom",
                    "type": tipo_entry.get(),
                    "from": self.nodo_id,
                    "to": destino_entry.get().upper(),
                    "ttl": int(ttl_entry.get()),
                    "headers": headers_json,
                    "payload": payload_text.get(1.0, tk.END).strip()
                }
                
                result = self.communication_mode.send_message(destino_entry.get().upper(), mensaje)
                
                if isinstance(result, tuple):
                    success, error = result
                    if success:
                        self.log_mensaje(f"→ Mensaje personalizado enviado a {destino_entry.get()}", "enviado")
                        ventana_msg.destroy()
                    else:
                        messagebox.showerror("Error", f"Error enviando: {error}")
                elif result:
                    self.log_mensaje(f"→ Mensaje personalizado enviado a {destino_entry.get()}", "enviado")
                    ventana_msg.destroy()
                else:
                    messagebox.showerror("Error", "Error enviando mensaje")
                    
            except json.JSONDecodeError:
                messagebox.showerror("Error", "Headers debe ser JSON válido")
            except Exception as e:
                messagebox.showerror("Error", f"Error: {e}")
        
        
        botones_frame = ttk.Frame(frame)
        botones_frame.grid(row=5, column=0, columnspan=2, pady=(10,0))
        
        ttk.Button(botones_frame, text="Enviar", command=enviar_personalizado).pack(side="left", padx=(0,5))
        ttk.Button(botones_frame, text="Cancelar", command=ventana_msg.destroy).pack(side="left")
    
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
        if self.communication_mode:
            self.desconectar()
        self.ventana.quit()
        self.ventana.destroy()

def main():
    import sys
    
    
    nodo_inicial = sys.argv[1].upper() if len(sys.argv) > 1 else "A"
    vecinos_inicial = sys.argv[2].split(",") if len(sys.argv) > 2 else ["B", "C", "D"]
    vecinos_inicial = [v.strip().upper() for v in vecinos_inicial]
    
    
    gui = HybridNetworkGUI()
    
    
    gui.nodo_entry.delete(0, tk.END)
    gui.nodo_entry.insert(0, nodo_inicial)
    
    gui.vecinos_entry.delete(0, tk.END)
    gui.vecinos_entry.insert(0, ",".join(vecinos_inicial))
    
    gui.log_mensaje(f"GUI iniciada - Nodo: {nodo_inicial}, Vecinos: {', '.join(vecinos_inicial)}", "sistema")
    gui.log_mensaje("Selecciona modo y presiona 'Conectar' para comenzar", "sistema")
    
    
    gui.iniciar()

if __name__ == "__main__":
    main()