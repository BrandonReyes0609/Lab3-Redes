import subprocess
import time
import sys
import os
import threading
import redis

TOPOLOGIA_EJEMPLO = {
    1: [2, 3],      
    2: [1, 4],      
    3: [1, 4, 5],  
    4: [2, 3, 5], 
    5: [3, 4]       
}

ALGORITMOS_REDIS = {
    'lsr': 'redis_lsr_node.py',
    'flooding': 'redis_flooding_node.py', 
    'dvr': 'redis_dvr_node.py'
}

def verificar_redis():
    try:
        r = redis.Redis(host='localhost', port=6379)
        r.ping()
        print("[TEST] Redis está corriendo correctamente")
        return True
    except:
        print("[ERROR] Redis no está disponible. Asegúrate de que Redis esté ejecutándose en localhost:6379")
        return False

def limpiar_redis():
    try:
        r = redis.Redis(host='localhost', port=6379)
        keys = r.keys('sec20.topologia1.*')
        if keys:
            r.delete(*keys)
        print("[TEST] Redis limpiado")
    except Exception as e:
        print(f"[WARNING] Error limpiando Redis: {e}")

def ejecutar_nodo_redis(algoritmo, numero_nodo, vecinos, archivo_script, email_personalizado="", prueba=""):
    try:
        vecinos_str = ','.join(map(str, vecinos))
        
        if email_personalizado:
            email = email_personalizado
        else:
            email = f"nodo{numero_nodo}@.com"
        
        cmd = ['python3', archivo_script, str(numero_nodo), vecinos_str, email]
        if prueba:
            cmd.append(prueba)
        
        print(f"[TEST] Iniciando nodo {numero_nodo} ({email}) con {algoritmo}")
        print(f"[TEST] Comando: {' '.join(cmd)}")
        
        proceso = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        return proceso
    except Exception as e:
        print(f"[ERROR] No se pudo iniciar nodo {numero_nodo} con {algoritmo}: {e}")
        return None

def probar_algoritmo_redis(algoritmo, topologia=None, configuracion_personalizada=None):
    print(f"\n{'='*70}")
    print(f"PROBANDO ALGORITMO CON REDIS: {algoritmo.upper()}")
    print(f"PROTOCOLO: sec20.topologia1.nodo<X> con IDs email")
    print(f"{'='*70}")
    
    if algoritmo not in ALGORITMOS_REDIS:
        print(f"[ERROR] Algoritmo {algoritmo} no encontrado")
        return
    
    archivo_script = ALGORITMOS_REDIS[algoritmo]
    
    if not os.path.exists(archivo_script):
        print(f"[ERROR] Archivo {archivo_script} no existe")
        return
    
    if not verificar_redis():
        return
    
    if topologia is None:
        topologia = TOPOLOGIA_EJEMPLO
    
    limpiar_redis()
    
    procesos = []
    
    try:
        print(f"[TEST] Usando topología: {topologia}")
        
        if configuracion_personalizada:
            print(f"[TEST] Configuración personalizada: {configuracion_personalizada}")
        
        for nodo, vecinos in topologia.items():
            email = ""
            prueba = ""
            
            if configuracion_personalizada and nodo in configuracion_personalizada:
                config = configuracion_personalizada[nodo]
                email = config.get('email', f"nodo{nodo}@.com")
                prueba = config.get('prueba', "")
            
            proceso = ejecutar_nodo_redis(algoritmo, nodo, vecinos, archivo_script, email, prueba)
            if proceso:
                procesos.append((nodo, proceso))
                time.sleep(2)  
        
        print(f"\n[TEST] Todos los nodos iniciados para {algoritmo}")
        print("[TEST] Dejando que los algoritmos se estabilicen...")
        
        if algoritmo == 'flooding':
            tiempo_espera = 15
        elif algoritmo == 'lsr':
            tiempo_espera = 45  
        elif algoritmo == 'dvr':
            tiempo_espera = 30  
        else:
            tiempo_espera = 20
        
        for i in range(tiempo_espera):
            print(f"[TEST] Esperando... {tiempo_espera-i} segundos restantes", end='\r')
            time.sleep(1)
        
        print(f"\n[TEST] Prueba de {algoritmo} completada")
        print("[TEST] Presiona Ctrl+C para terminar y continuar")
        
        mostrar_logs_tiempo_real = input("\n[TEST] ¿Mostrar logs en tiempo real? (y/n): ").lower() == 'y'
        
        if mostrar_logs_tiempo_real:
            print("[TEST] Mostrando logs (Ctrl+C para continuar)...")
            try:
                while True:
                    time.sleep(1)
                    for nodo, proceso in procesos:
                        if proceso.poll() is None: 
                            try:
                                output = proceso.stdout.readline()
                                if output:
                                    print(f"[NODO {nodo}] {output.strip()}")
                            except:
                                pass
            except KeyboardInterrupt:
                print(f"\n[TEST] Deteniendo visualización de logs...")
        
    except KeyboardInterrupt:
        print(f"\n[TEST] Interrumpido por usuario")
        
    finally:
        print(f"[TEST] Terminando procesos de {algoritmo}...")
        for nodo, proceso in procesos:
            try:
                proceso.terminate()
                proceso.wait(timeout=5)
                print(f"[TEST] Nodo {nodo} terminado")
            except:
                proceso.kill()
                print(f"[TEST] Nodo {nodo} forzado a terminar")
        
        limpiar_redis()

def crear_topologia_personalizada():
    print("\n=== CREAR TOPOLOGÍA PERSONALIZADA ===")
    print("Formato: nodo:vecino1,vecino2,... (ejemplo: 1:2,3)")
    print("Escribe 'done' cuando termines")
    
    topologia = {}
    
    while True:
        entrada = input("Nodo y vecinos: ").strip()
        if entrada.lower() == 'done':
            break
        
        try:
            nodo_str, vecinos_str = entrada.split(':')
            nodo = int(nodo_str)
            vecinos = [int(v) for v in vecinos_str.split(',')]
            topologia[nodo] = vecinos
            print(f"  Agregado: Nodo {nodo} -> Vecinos {vecinos}")
        except:
            print("  Formato inválido. Use: nodo:vecino1,vecino2,...")
    
    return topologia if topologia else None

def crear_configuracion_personalizada():
    print("\n=== CONFIGURACIÓN PERSONALIZADA ===")
    print("Personalizar emails y pruebas para cada nodo")
    print("Formato: nodo:email:prueba (ejemplo: 1:us@.com:prueba1)")
    print("Si no quiere prueba: nodo:email: (ejemplo: 1:us@.com:)")
    print("Escribe 'done' cuando termines")
    
    configuracion = {}
    
    while True:
        entrada = input("Configuración nodo: ").strip()
        if entrada.lower() == 'done':
            break
        
        try:
            partes = entrada.split(':')
            if len(partes) >= 2:
                nodo = int(partes[0])
                email = partes[1] if partes[1] else f"nodo{nodo}@.com"
                prueba = partes[2] if len(partes) > 2 else ""
                
                configuracion[nodo] = {
                    'email': email,
                    'prueba': prueba
                }
                print(f"  Configurado: Nodo {nodo} -> {email} (prueba: '{prueba}')")
        except:
            print("  Formato inválido. Use: nodo:email:prueba")
    
    return configuracion if configuracion else None

def configuracion_ejemplo():
    print("\n=== CONFIGURACIÓN DE EJEMPLO ===")
    print("Usando topología ejemplo con configuración personalizada:")
    
    topologia = {
        1: [2, 3],
        2: [1, 4], 
        3: [1, 4],
        4: [2, 3]
    }
    
    configuracion = {
        1: {'email': 'us@.com', 'prueba': 'prueba1'},
        2: {'email': 'node2@test.com', 'prueba': ''},
        3: {'email': 'whatever@.com', 'prueba': 'test'},
        4: {'email': 'nodo4@.com', 'prueba': 'final'}
    }
    
    print("Topología:", topologia)
    print("Configuración:", configuracion)
    
    algoritmo = input("¿Qué algoritmo probar? (lsr/flooding/dvr): ").lower()
    if algoritmo in ALGORITMOS_REDIS:
        probar_algoritmo_redis(algoritmo, topologia, configuracion)
    else:
        print(f"Algoritmo '{algoritmo}' no válido")

def mostrar_ayuda():
    print("Script de pruebas para algoritmos de enrutamiento con Redis")
    print("\nProtocolo actualizado:")
    print("  - IDs de nodo: formato email (us@.com, nodo1@.com, etc.)")
    print("  - Canales: sec20.topologia1.nodo<X>.<prueba>") 
    print("  - Headers: letras A, B, C representando routers")
    print("\nRequisitos:")
    print("  - Redis server corriendo en localhost:6379")
    print("  - Archivos de implementación de algoritmos")
    print("\nUso:")
    print("  python test_redis_algorithms.py <algoritmo>")
    print("  python test_redis_algorithms.py all")
    print("  python test_redis_algorithms.py custom")
    print("  python test_redis_algorithms.py ejemplo")
    print("\nAlgoritmos disponibles:")
    for alg in ALGORITMOS_REDIS.keys():
        print(f"  - {alg}")
    print("\nEjemplos:")
    print("  python test_redis_algorithms.py lsr")
    print("  python test_redis_algorithms.py ejemplo")
    print("  python test_redis_algorithms.py custom")

def main():
    if len(sys.argv) != 2:
        mostrar_ayuda()
        sys.exit(1)
    
    argumento = sys.argv[1].lower()
    
    if argumento == 'help' or argumento == '-h':
        mostrar_ayuda()
        return
    
    if not verificar_redis():
        print("\n[ERROR] Inicia Redis server antes de continuar")
        print("Ubuntu/Debian: sudo service redis-server start")
        print("macOS: redis-server")
        print("Windows: redis-server.exe")
        return
    
    if argumento == 'all':
        print("Probando todos los algoritmos secuencialmente...")
        for algoritmo in ALGORITMOS_REDIS.keys():
            probar_algoritmo_redis(algoritmo)
            if algoritmo != list(ALGORITMOS_REDIS.keys())[-1]:
                input("\n[TEST] Presiona Enter para continuar con el siguiente algoritmo...")
    
    elif argumento == 'custom':
        topologia_personalizada = crear_topologia_personalizada()
        configuracion_personalizada = None
        
        if topologia_personalizada:
            personalizar_config = input("¿Personalizar emails y pruebas? (y/n): ").lower() == 'y'
            if personalizar_config:
                configuracion_personalizada = crear_configuracion_personalizada()
            
            print(f"Topología creada: {topologia_personalizada}")
            algoritmo = input("¿Qué algoritmo probar? (lsr/flooding/dvr): ").lower()
            if algoritmo in ALGORITMOS_REDIS:
                probar_algoritmo_redis(algoritmo, topologia_personalizada, configuracion_personalizada)
            else:
                print(f"Algoritmo '{algoritmo}' no válido")
        else:
            print("No se creó ninguna topología")
    
    elif argumento == 'ejemplo':
        configuracion_ejemplo()
    
    elif argumento in ALGORITMOS_REDIS:
        probar_algoritmo_redis(argumento)
    
    else:
        print(f"[ERROR] Argumento '{argumento}' no reconocido")
        mostrar_ayuda()
        sys.exit(1)

if __name__ == "__main__":
    main()