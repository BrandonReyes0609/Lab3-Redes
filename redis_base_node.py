import redis
import json
import threading
import time
import uuid
import heapq
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from collections import defaultdict

class FlexiblePacket:
    def __init__(self, proto: str, packet_type: str, from_addr: str, to_addr: str, 
                 ttl: int = 5, headers: Union[List[str], Dict[str, Any], None] = None, 
                 payload: Any = ""):
        self.proto = proto
        self.type = packet_type
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.ttl = ttl
        self.headers = headers if headers is not None else []
        self.payload = payload
    
    def is_headers_dict(self) -> bool:
        return isinstance(self.headers, dict)
    
    def get_msg_id(self) -> Optional[str]:
        if self.is_headers_dict():
            return self.headers.get("msg_id")
        return None
    
    def ensure_msg_id(self) -> str:
        if self.is_headers_dict() and self.headers.get("msg_id"):
            return self.headers["msg_id"]
        
        new_id = str(uuid.uuid4())[:8]
        if self.is_headers_dict():
            self.headers["msg_id"] = new_id
        else:
            path = list(self.headers) if isinstance(self.headers, list) else []
            self.headers = {"msg_id": new_id, "path": path}
        
        return new_id
    
    def get_path(self) -> List[str]:
        if self.is_headers_dict():
            return list(self.headers.get("path", []))
        elif isinstance(self.headers, list):
            return list(self.headers)
        return []
    
    def set_path(self, path: List[str]):
        if self.is_headers_dict():
            self.headers["path"] = list(path)
        else:
            self.headers = list(path)
    
    def to_dict(self) -> Dict:
        return {
            "proto": self.proto,
            "type": self.type,
            "from": self.from_addr,
            "to": self.to_addr,
            "ttl": self.ttl,
            "headers": self.headers,
            "payload": self.payload
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "FlexiblePacket":
        data = json.loads(json_str)
        return cls(
            proto=data.get("proto", "unknown"),
            packet_type=data.get("type", "unknown"),
            from_addr=data.get("from", "unknown"),
            to_addr=data.get("to", "unknown"),
            ttl=data.get("ttl", 5),
            headers=data.get("headers", []),
            payload=data.get("payload", "")
        )
    
    @classmethod
    def from_dict(cls, data: Dict) -> "FlexiblePacket":
        return cls(
            proto=data.get("proto", "unknown"),
            packet_type=data.get("type", "unknown"),
            from_addr=data.get("from", "unknown"),
            to_addr=data.get("to", "unknown"),
            ttl=data.get("ttl", 5),
            headers=data.get("headers", []),
            payload=data.get("payload", "")
        )

class ConfigurableRedisNode(ABC):
    def __init__(self, config_file: str):
        self.config = self.load_config(config_file)
        
        self.node_id = self.config.get("node_id", "unknown")
        self.redis_host = self.config.get("redis", {}).get("host", "localhost")
        self.redis_port = self.config.get("redis", {}).get("port", 6379)
        self.redis_password = self.config.get("redis", {}).get("password", "")
        
        self.my_channels = self.config.get("channels", {}).get("subscribe", [])
        self.neighbor_channels = self.config.get("channels", {}).get("neighbors", {})
        
        self.message_format = self.config.get("message_format", "flexible")
        self.node_name_format = self.config.get("node_name_format", "letters")
        
        self.redis_client = redis.Redis(
            host=self.redis_host, 
            port=self.redis_port, 
            password=self.redis_password,
            decode_responses=True
        )
        self.pubsub = self.redis_client.pubsub()
        
        self.activo = True
        self.mensajes_procesados = set()
        
        print(f"[{self.node_id}] Nodo configurable inicializado")
        print(f"[{self.node_id}] Canales suscritos: {self.my_channels}")
        print(f"[{self.node_id}] Formato: {self.message_format}")
    
    def load_config(self, config_file: str) -> Dict:
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando configuración: {e}")
            return {}
    
    def subscribe_to_channels(self):
        for channel in self.my_channels:
            try:
                self.pubsub.subscribe(channel)
                print(f"[{self.node_id}] Suscrito a: {channel}")
            except Exception as e:
                print(f"[{self.node_id}] Error suscribiéndose a {channel}: {e}")
    
    def create_packet(self, packet_type: str, to_addr: str, payload: Any, 
                     ttl: int = 5, custom_headers: Optional[Dict] = None) -> FlexiblePacket:
        if self.message_format == "simple":
            headers = [self.get_node_name()]
        elif self.message_format == "extended":
            headers = {
                "msg_id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().isoformat(),
                "path": [self.get_node_name()]
            }
            if custom_headers:
                headers.update(custom_headers)
        else:
            headers = custom_headers or {"msg_id": str(uuid.uuid4())[:8], "path": [self.get_node_name()]}
        
        return FlexiblePacket(
            proto=self.get_protocol_name(),
            packet_type=packet_type,
            from_addr=self.get_node_name(),
            to_addr=to_addr,
            ttl=ttl,
            headers=headers,
            payload=payload
        )
    
    def get_node_name(self) -> str:
        if self.node_name_format == "letters" and self.node_id.isalpha():
            return self.node_id.upper()
        elif self.node_name_format == "numbers":
            return str(ord(self.node_id.upper()) - ord('A') + 1) if self.node_id.isalpha() else self.node_id
        elif self.node_name_format == "email":
            return f"{self.node_id.lower()}@.com"
        else:
            return f"sec20.topologia1.{self.node_id}"
    
    def detect_message_format(self, packet_data: Dict) -> str:
        headers = packet_data.get("headers", [])
        from_addr = packet_data.get("from", "")
        
        if isinstance(headers, dict) and "msg_id" in headers:
            return "extended"
        elif isinstance(headers, list):
            return "simple"
        elif "@" in from_addr:
            return "email"
        elif "sec" in from_addr:
            return "full_id"
        else:
            return "unknown"
    
    def normalize_packet(self, packet_data: Dict) -> FlexiblePacket:
        packet = FlexiblePacket.from_dict(packet_data)
        packet.ensure_msg_id()
        return packet
    
    def send_to_channel(self, packet: FlexiblePacket, channel: str) -> bool:
        try:
            self.redis_client.publish(channel, packet.to_json())
            print(f"[{self.node_id}] Enviado a {channel}: {packet.type}")
            return True
        except Exception as e:
            print(f"[{self.node_id}] Error enviando a {channel}: {e}")
            return False
    
    def broadcast_packet(self, packet: FlexiblePacket) -> int:
        enviados = 0
        for neighbor_id, channel in self.neighbor_channels.items():
            if self.send_to_channel(packet, channel):
                enviados += 1
        return enviados
    
    def process_received_message(self, channel: str, message_data: str):
        try:
            packet_data = json.loads(message_data)
            packet = self.normalize_packet(packet_data)
            
            msg_id = packet.get_msg_id()
            if msg_id and msg_id in self.mensajes_procesados:
                return
            if msg_id:
                self.mensajes_procesados.add(msg_id)
            
            if packet.from_addr == self.get_node_name():
                return
            
            print(f"[{self.node_id}] Recibido de {channel}: {packet.type} de {packet.from_addr}")
            
            self.handle_packet(packet, channel)
            
        except Exception as e:
            print(f"[{self.node_id}] Error procesando mensaje: {e}")
    
    def escuchar_mensajes(self):
        try:
            for mensaje in self.pubsub.listen():
                if not self.activo:
                    break
                if mensaje['type'] == 'message':
                    self.process_received_message(mensaje['channel'], mensaje['data'])
        except Exception as e:
            print(f"[{self.node_id}] Error en listener: {e}")
        finally:
            self.pubsub.close()
    
    def iniciar(self):
        print(f"[{self.node_id}] Iniciando nodo configurable...")
        
        self.subscribe_to_channels()
        
        hilo_listener = threading.Thread(target=self.escuchar_mensajes, daemon=True)
        hilo_listener.start()
        
        time.sleep(1)
        
        self.inicializacion_especifica()
        
        try:
            while self.activo:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.node_id}] Deteniendo nodo...")
            self.activo = False
    
    @abstractmethod
    def get_protocol_name(self) -> str:
        pass
    
    @abstractmethod
    def handle_packet(self, packet: FlexiblePacket, received_channel: str):
        pass
    
    @abstractmethod
    def inicializacion_especifica(self):
        pass

class InteroperableLSRNode(ConfigurableRedisNode):
    def __init__(self, config_file: str):
        super().__init__(config_file)
        self.routing_table = {}
        self.neighbor_states = {}
        self.lsa_database = {}
        self.my_sequence_number = 0
        self.topology = self.config.get("topology", {})
        self.last_hello_time = 0
        self.last_lsa_time = 0
    
    def get_protocol_name(self) -> str:
        return "lsr"
    
    def handle_packet(self, packet: FlexiblePacket, received_channel: str):
        if packet.type == "hello":
            self.handle_hello(packet, received_channel)
        elif packet.type == "info" or packet.type == "lsa":
            self.handle_lsa(packet, received_channel)
        elif packet.type == "message":
            self.handle_message(packet, received_channel)
    
    def handle_hello(self, packet: FlexiblePacket, channel: str):
        print(f"[{self.node_id}] HELLO de {packet.from_addr}")
        
        self.neighbor_states[packet.from_addr] = {
            'last_seen': time.time(),
            'channel': channel,
            'alive': True
        }
    
    def handle_lsa(self, packet: FlexiblePacket, channel: str):
        print(f"[{self.node_id}] LSA de {packet.from_addr}")
        
        try:
            if isinstance(packet.payload, str):
                lsa_data = json.loads(packet.payload)
            else:
                lsa_data = packet.payload
            
            origin = lsa_data.get("origin", packet.from_addr)
            sequence = lsa_data.get("sequence", 0)
            
            current_lsa = self.lsa_database.get(origin)
            if current_lsa and sequence <= current_lsa.get('sequence', 0):
                return
            
            self.lsa_database[origin] = {
                'data': lsa_data,
                'received': time.time(),
                'channel': channel,
                'sequence': sequence
            }
            
            self.calculate_routing_table()
            
            if packet.ttl > 1:
                packet.ttl -= 1
                self.broadcast_packet(packet)
                
        except Exception as e:
            print(f"[{self.node_id}] Error procesando LSA: {e}")
    
    def handle_message(self, packet: FlexiblePacket, channel: str):
        if packet.to_addr == self.get_node_name():
            print(f"[{self.node_id}] MENSAJE RECIBIDO de {packet.from_addr}: '{packet.payload}'")
        else:
            next_hop = self.routing_table.get(packet.to_addr)
            if next_hop and packet.ttl > 1:
                next_channel = self.neighbor_channels.get(next_hop)
                if next_channel:
                    packet.ttl -= 1
                    print(f"[{self.node_id}] Reenviando mensaje: {packet.from_addr} -> {packet.to_addr} via {next_hop}")
                    self.send_to_channel(packet, next_channel)
                else:
                    print(f"[{self.node_id}] No se encontró canal para {next_hop}")
            else:
                print(f"[{self.node_id}] No hay ruta a {packet.to_addr}")
    
    def calculate_routing_table(self):
        graph = defaultdict(dict)
        
        for neighbor in self.topology.get(self.node_id, []):
            if neighbor in self.neighbor_states and self.neighbor_states[neighbor].get('alive', False):
                graph[self.get_node_name()][neighbor] = 1
        
        for origin, lsa_info in self.lsa_database.items():
            lsa_data = lsa_info['data']
            neighbors = lsa_data.get('neighbors', {})
            for neighbor, cost in neighbors.items():
                graph[origin][neighbor] = cost
        
        if not graph:
            return
        
        distances = {node: float('inf') for node in graph}
        distances[self.get_node_name()] = 0
        predecessors = {}
        unvisited = set(graph.keys())
        
        while unvisited:
            current = min(unvisited, key=lambda x: distances[x])
            if distances[current] == float('inf'):
                break
            
            unvisited.remove(current)
            
            for neighbor, weight in graph[current].items():
                if neighbor in unvisited:
                    alt = distances[current] + weight
                    if alt < distances[neighbor]:
                        distances[neighbor] = alt
                        predecessors[neighbor] = current
        
        new_routing_table = {}
        for dest, dist in distances.items():
            if dest != self.get_node_name() and dist != float('inf'):
                next_hop = dest
                temp = dest
                while predecessors.get(temp) != self.get_node_name() and temp in predecessors:
                    temp = predecessors[temp]
                if predecessors.get(temp) == self.get_node_name():
                    next_hop = temp
                new_routing_table[dest] = next_hop
        
        self.routing_table = new_routing_table
        self.print_routing_table()
    
    def print_routing_table(self):
        print(f"[{self.node_id}] Tabla de enrutamiento actualizada:")
        for dest, next_hop in self.routing_table.items():
            print(f"   {dest} -> {next_hop}")
    
    def send_hello(self):
        if time.time() - self.last_hello_time > 10:
            hello_packet = self.create_packet("hello", "broadcast", "")
            self.broadcast_packet(hello_packet)
            self.last_hello_time = time.time()
    
    def send_lsa(self):
        if time.time() - self.last_lsa_time > 30:
            self.my_sequence_number += 1
            
            neighbors = {}
            for neighbor in self.topology.get(self.node_id, []):
                if neighbor in self.neighbor_states and self.neighbor_states[neighbor].get('alive', False):
                    neighbors[neighbor] = 1
            
            lsa_data = {
                "origin": self.get_node_name(),
                "sequence": self.my_sequence_number,
                "neighbors": neighbors,
                "timestamp": time.time()
            }
            
            lsa_packet = self.create_packet("info", "broadcast", json.dumps(lsa_data))
            self.broadcast_packet(lsa_packet)
            self.last_lsa_time = time.time()
    
    def check_neighbor_timeouts(self):
        current_time = time.time()
        for neighbor, state in self.neighbor_states.items():
            if current_time - state['last_seen'] > 30:
                if state['alive']:
                    state['alive'] = False
                    print(f"[{self.node_id}] Vecino {neighbor} timeout")
                    self.calculate_routing_table()
    
    def periodic_tasks(self):
        while self.activo:
            time.sleep(5)
            self.send_hello()
            self.send_lsa()
            self.check_neighbor_timeouts()
    
    def inicializacion_especifica(self):
        time.sleep(2)
        
        hello_packet = self.create_packet("hello", "broadcast", "")
        self.broadcast_packet(hello_packet)
        
        periodic_thread = threading.Thread(target=self.periodic_tasks, daemon=True)
        periodic_thread.start()
        
        print(f"[{self.node_id}] LSR inicializado")

def main():
    import sys
    
    if len(sys.argv) != 2:
        sys.exit(1)
    
    config_file = sys.argv[1]
    nodo = InteroperableLSRNode(config_file)
    nodo.iniciar()

if __name__ == "__main__":
    main()