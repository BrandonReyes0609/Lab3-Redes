import subprocess
import time
import json
import os
import sys
import signal
import socket
import tempfile

class NetworkTester:
    def __init__(self):
        self.processes = []
        self.base_port = 6000
        
    def find_free_ports(self, count=4):
        free_ports = []
        start_port = self.base_port
        
        for port in range(start_port, start_port + 20):
            if self.check_port(port):
                free_ports.append(port)
                if len(free_ports) >= count:
                    break
        
        return free_ports
        
    def check_port(self, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            return result != 0
        except:
            return False
    
    def create_modified_script(self, original_script, port_mapping):
        with open(original_script, 'r') as f:
            content = f.read()
        
        content = content.replace('PUERTO_BASE = 5000', f'PUERTO_BASE = {self.base_port}')
        content = content.replace('TIEMPO_ESPERA_INICIAL = 3', 'TIEMPO_ESPERA_INICIAL = 10')
        
        temp_script = f"temp_{original_script}"
        with open(temp_script, 'w') as f:
            f.write(content)
        
        return temp_script
    
    def create_topology(self, topology_type="linear"):
        topologies = {
            "linear": {
                "config": {
                    "A": ["B"],
                    "B": ["A", "C"],
                    "C": ["B", "D"],
                    "D": ["C"]
                }
            },
            "ring": {
                "config": {
                    "A": ["B", "D"],
                    "B": ["A", "C"],
                    "C": ["B", "D"],
                    "D": ["C", "A"]
                }
            },
            "star": {
                "config": {
                    "A": ["B", "C", "D"],
                    "B": ["A"],
                    "C": ["A"],
                    "D": ["A"]
                }
            }
        }
        
        filename = "test_topology.json"
        with open(filename, 'w') as f:
            json.dump(topologies[topology_type], f, indent=2)
        return filename
    
    def launch_nodes(self, script_name, topology_file, free_ports, nodes=["A", "B", "C", "D"]):
        print(f"Iniciando nodos: {' '.join(nodes)}")
        print(f" Usando puertos: {free_ports}")
        print("=" * 50)
        
        temp_script = self.create_modified_script(script_name, {})
        
        for i, node in enumerate(nodes):
            try:
                expected_port = free_ports[i]
                
                env = os.environ.copy()
                env['PYTHONUNBUFFERED'] = '1'
                
                process = subprocess.Popen([
                    sys.executable, "-u", temp_script, node, topology_file
                ], env=env)
                
                self.processes.append(process)
                print(f" Nodo {node} iniciado (PID: {process.pid}, Puerto: {expected_port})")
                
                time.sleep(2)
                
                if process.poll() is not None:
                    print(f" Nodo {node} terminó inesperadamente")
                    return False, temp_script
                    
            except Exception as e:
                print(f" Error iniciando nodo {node}: {e}")
                return False, temp_script
        
        print("=" * 50)
        return True, temp_script
    
    def monitor_test(self, duration):
        print(f" Monitoreando por {duration} segundos...")
        print(" Los mensajes aparecen en la terminal en tiempo real")
        print(" Presiona Ctrl+C para terminar antes")
        print("=" * 50)
        
        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\n  Interrumpido por usuario")
        
        print("=" * 50)
        print(" Monitoreo completado")
    
    def cleanup(self, temp_script=None):
        print("🧹 Limpiando procesos...")
        for i, process in enumerate(self.processes):
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                    print(f" Proceso {i+1} terminado")
                except:
                    try:
                        process.kill()
                        process.wait(timeout=1)
                        print(f"  Proceso {i+1} forzado a terminar")
                    except:
                        print(f" No se pudo terminar proceso {i+1}")
        
        self.processes.clear()
        
        if temp_script and os.path.exists(temp_script):
            os.remove(temp_script)
            print(f"  Script temporal eliminado: {temp_script}")
        
        time.sleep(1)
        
        if os.path.exists("test_topology.json"):
            choice = input("¿Borrar archivo de topología? (y/N): ").lower().strip()
            if choice == 'y':
                os.remove("test_topology.json")
                print("  Archivo eliminado")
            else:
                print(" Archivo conservado: test_topology.json")
    
    def run_test(self, algorithm, topology="linear", duration=20):
        script_map = {
            "flooding": "flooding_node_explicit.py",
            "linkstate": "link_state.py", 
            "vector": "vector.py",
            "dijkstra": "dijkstra.py"
        }
        
        if algorithm not in script_map:
            print(f" Algoritmo '{algorithm}' no válido")
            print(f" Disponibles: {', '.join(script_map.keys())}")
            return
        
        script_name = script_map[algorithm]
        
        if not os.path.exists(script_name):
            print(f" Script '{script_name}' no encontrado")
            print(" Archivos Python disponibles:")
            for f in sorted(os.listdir('.')):
                if f.endswith('.py'):
                    print(f"    {f}")
            return
        
        print(f"PRUEBA: {algorithm.upper()} con topología {topology.upper()}")
        print(f"Script: {script_name}")
        print(f"Duración: {duration} segundos")
        
        print("Buscando puertos libres...")
        free_ports = self.find_free_ports(4)
        
        if len(free_ports) < 4:
            print(f"Solo {len(free_ports)} puertos libres encontrados, necesito 4")
            print("Puertos libres encontrados:", free_ports)
            return
        
        print(f"Usando puertos: {free_ports}")
        
        topology_file = self.create_topology(topology)
        print(f"Topología creada: {topology_file}")
        
        success, temp_script = self.launch_nodes(script_name, topology_file, free_ports)
        
        if success:
            print("⏳ Esperando que todos los nodos estén listos...")
            time.sleep(8)
            self.monitor_test(duration)
        else:
            print("Falló el lanzamiento de nodos")
        
        self.cleanup(temp_script)

def signal_handler(signum, frame):
    print("\nSeñal de interrupción recibida")
    if 'tester' in globals():
        tester.cleanup()
    sys.exit(0)

def manual_port_killer():
    print("LIBERADOR MANUAL DE PUERTOS")
    print("=" * 30)
    
    ports_to_kill = [5000, 5001, 5002, 5003, 6000, 6001, 6002, 6003]
    
    for port in ports_to_kill:
        try:
            result = subprocess.run(['lsof', '-ti', f':{port}'], 
                                  capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        subprocess.run(['kill', '-9', pid], capture_output=True)
                        print(f"Proceso {pid} terminado en puerto {port}")
            else:
                print(f"Puerto {port} libre")
        except Exception as e:
            print(f"Error en puerto {port}: {e}")
    
    print("Limpieza manual completada")

def main():
    global tester
    
    if len(sys.argv) > 1 and sys.argv[1] == "--kill":
        manual_port_killer()
        return
    
    tester = NetworkTester()
    signal.signal(signal.SIGINT, signal_handler)
    
    if len(sys.argv) < 2:
        print("SCRIPT DE PRUEBA - ALGORITMOS DE ENRUTAMIENTO")
        print("=" * 55)
        print("Uso: python alt_test.py <algoritmo> [topología] [duración]")
        print("     python alt_test.py --kill (para liberar puertos)")
        print("")
        print("Algoritmos disponibles:")
        print("  flooding   - Algoritmo de inundación")  
        print("  linkstate  - Link State Routing")
        print("  vector     - Distance Vector")
        print("  dijkstra   - Algoritmo Dijkstra")
        print("")
        print("Topologías disponibles:")
        print("  linear     - A-B-C-D (por defecto)")
        print("  ring       - A-B-C-D-A") 
        print("  star       - A conectado a B,C,D")
        print("")
        print("Ejemplos:")
        print("  python alt_test.py flooding")
        print("  python alt_test.py linkstate ring 30")
        print("  python alt_test.py --kill")
        return
    
    algorithm = sys.argv[1].lower()
    topology = sys.argv[2].lower() if len(sys.argv) > 2 else "linear"
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    
    tester.run_test(algorithm, topology, duration)

if __name__ == "__main__":
    main()