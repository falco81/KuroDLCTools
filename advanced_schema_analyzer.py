#!/usr/bin/env python3
"""
Advanced Schema Analyzer for Kuro DLC Tables
Analyzuje JSON a TBL soubory pro určení přesné binární struktury

GitHub eArmada8/kuro_dlc_tool
"""

import json
import struct
import os
import sys
from typing import Dict, List, Any, Tuple, Optional

class AdvancedSchemaAnalyzer:
    def __init__(self, schema_file='kurodlc_schema.json'):
        self.schema_file = schema_file
        self.schemas = []
        self.load_existing_schemas()
    
    def load_existing_schemas(self):
        """Načte existující schéma ze souboru"""
        if os.path.exists(self.schema_file):
            with open(self.schema_file, 'r', encoding='utf-8') as f:
                self.schemas = json.load(f)
            print(f"✓ Načteno {len(self.schemas)} existujících schémat")
        else:
            print(f"⚠ Soubor {self.schema_file} neexistuje, bude vytvořen nový")
    
    def analyze_json_structure(self, json_file: str) -> Dict[str, Dict[str, Any]]:
        """Analyzuje strukturu JSON souboru"""
        print(f"\n{'─'*60}")
        print(f"📄 Analyzuji JSON: {os.path.basename(json_file)}")
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'headers' not in data or 'data' not in data:
            print(f"  ⚠ VAROVÁNÍ: Nestandardní struktura")
            return {}
        
        json_info = {}
        
        for header in data['headers']:
            table_name = header['name']
            schema_version = header.get('schema', 'Unknown')
            
            # Najdi data
            table_data = None
            for data_section in data['data']:
                if data_section['name'] == table_name:
                    table_data = data_section['data']
                    break
            
            if not table_data or len(table_data) == 0:
                continue
            
            keys = list(table_data[0].keys())
            value_types = self.infer_value_types(table_data, keys)
            
            json_info[table_name] = {
                'schema_version': schema_version,
                'keys': keys,
                'value_types': value_types,
                'num_entries': len(table_data),
                'sample_data': table_data[0]
            }
            
            print(f"  ├─ {table_name} ({schema_version})")
            print(f"  │  ├─ Záznamy: {len(table_data)}")
            print(f"  │  ├─ Klíče: {len(keys)}")
            print(f"  │  └─ Typy: {value_types}")
        
        return json_info
    
    def infer_value_types(self, table_data: List[Dict], keys: List[str]) -> str:
        """
        Odvodí typy hodnot z dat
        n = numeric, t = text, a = array (u32), b = array (u16)
        """
        value_types = []
        
        for key in keys:
            samples = [entry.get(key) for entry in table_data[:min(20, len(table_data))]]
            
            if all(isinstance(v, (int, float)) for v in samples):
                value_types.append('n')
            elif all(isinstance(v, str) for v in samples):
                value_types.append('t')
            elif all(isinstance(v, list) for v in samples):
                value_types.append('a')  # Default, může být 'b' podle TBL
            else:
                value_types.append('n')
        
        return ''.join(value_types)
    
    def analyze_tbl_structure(self, tbl_file: str) -> Dict[str, Dict[str, Any]]:
        """Analyzuje binární strukturu TBL souboru"""
        print(f"\n{'─'*60}")
        print(f"🔧 Analyzuji TBL: {os.path.basename(tbl_file)}")
        
        tbl_info = {}
        
        with open(tbl_file, 'rb') as f:
            magic = f.read(4)
            if magic != b'#TBL':
                print(f"  ✗ CHYBA: Neplatný TBL soubor")
                return tbl_info
            
            num_sections, = struct.unpack("<I", f.read(4))
            print(f"  ├─ Počet tabulek: {num_sections}")
            
            # Načti všechny hlavičky
            headers = []
            for i in range(num_sections):
                table_name = f.read(64).replace(b'\x00', b'').decode('utf-8')
                crc, start_offset, entry_length, num_entries = struct.unpack("<4I", f.read(16))
                
                headers.append({
                    'name': table_name,
                    'crc': crc,
                    'start_offset': start_offset,
                    'entry_length': entry_length,
                    'num_entries': num_entries
                })
                
                print(f"  │")
                print(f"  ├─ {table_name}")
                print(f"  │  ├─ Entry length: {entry_length} bytes")
                print(f"  │  ├─ Entries: {num_entries}")
                print(f"  │  └─ Offset: 0x{start_offset:X}")
            
            # Analyzuj datovou sekci pro určení offsetů
            for header in headers:
                f.seek(header['start_offset'])
                
                # Přečti první záznam
                raw_entry = f.read(header['entry_length'])
                
                tbl_info[header['name']] = {
                    'entry_length': header['entry_length'],
                    'num_entries': header['num_entries'],
                    'start_offset': header['start_offset'],
                    'crc': header['crc'],
                    'raw_first_entry': raw_entry
                }
        
        return tbl_info
    
    def deduce_struct_pattern(self, json_data: Dict[str, Any], 
                             tbl_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        Dedukuje struct pattern porovnáním JSON a TBL dat
        Vrací (struct_pattern, refined_value_types)
        """
        keys = json_data['keys']
        value_types = list(json_data['value_types'])
        entry_length = tbl_data['entry_length']
        sample = json_data['sample_data']
        
        # Zkus různé kombinace struct patterns
        patterns = self.generate_pattern_candidates(keys, value_types, entry_length)
        
        best_pattern = None
        best_value_types = value_types
        
        for pattern, vtypes in patterns:
            try:
                size = struct.calcsize(pattern)
                if size == entry_length:
                    best_pattern = pattern
                    best_value_types = vtypes
                    break
            except struct.error:
                continue
        
        if best_pattern is None:
            # Fallback: jednoduchý pattern
            best_pattern = self.create_simple_pattern(entry_length)
            print(f"    ⚠ Použit fallback pattern")
        
        return best_pattern, ''.join(best_value_types)
    
    def generate_pattern_candidates(self, keys: List[str], value_types: List[str], 
                                   target_length: int) -> List[Tuple[str, List[str]]]:
        """Generuje kandidáty na struct pattern"""
        candidates = []
        
        # Základní typy podle value_types
        type_map = {
            'n': ['B', 'H', 'I', 'Q', 'f'],  # byte, short, int, long, float
            't': ['Q'],  # offset (8 bytes)
            'a': ['2Q'],  # offset + count (16 bytes)
            'b': ['2Q']   # offset + count (16 bytes)
        }
        
        def recurse(index: int, current_pattern: List[str], 
                   current_vtypes: List[str], current_size: int):
            if index >= len(keys):
                if current_size == target_length:
                    pattern_str = '<' + ''.join(current_pattern)
                    candidates.append((pattern_str, current_vtypes))
                return
            
            vtype = value_types[index]
            
            for type_code in type_map.get(vtype, ['I']):
                try:
                    if type_code == '2Q':
                        size_add = 16
                    else:
                        size_add = struct.calcsize('<' + type_code)
                    
                    new_size = current_size + size_add
                    
                    if new_size <= target_length:
                        recurse(index + 1, 
                               current_pattern + [type_code],
                               current_vtypes + [vtype],
                               new_size)
                except struct.error:
                    continue
        
        # Začni rekurzi
        recurse(0, [], [], 0)
        
        return candidates[:10]  # Limituj na prvních 10 kandidátů
    
    def create_simple_pattern(self, length: int) -> str:
        """Vytvoří jednoduchý pattern pokud automatická detekce selže"""
        # Použij unsigned int (4 bytes) pro většinu
        num_ints = length // 4
        remainder = length % 4
        
        pattern = '<' + f'{num_ints}I'
        
        if remainder > 0:
            pattern += f'{remainder}B'
        
        return pattern
    
    def match_and_merge(self, json_file: str, tbl_file: str, 
                       game_version: str = "") -> Dict[str, Dict[str, Any]]:
        """Porovná a sloučí informace z JSON a TBL"""
        json_info = self.analyze_json_structure(json_file)
        tbl_info = self.analyze_tbl_structure(tbl_file)
        
        merged = {}
        
        print(f"\n{'─'*60}")
        print(f"🔍 Slučuji informace...")
        
        for table_name in json_info:
            if table_name not in tbl_info:
                print(f"  ⚠ {table_name}: Není v TBL")
                continue
            
            json_data = json_info[table_name]
            tbl_data = tbl_info[table_name]
            
            # Dedukuj struct pattern
            struct_pattern, value_types = self.deduce_struct_pattern(json_data, tbl_data)
            
            merged[table_name] = {
                'table_header': table_name,
                'schema_version': json_data['schema_version'],
                'game_version': game_version,
                'schema_length': tbl_data['entry_length'],
                'struct_pattern': struct_pattern,
                'keys': json_data['keys'],
                'value_types': value_types,
                'num_entries': json_data['num_entries']
            }
            
            print(f"  ✓ {table_name}")
            print(f"    ├─ Pattern: {struct_pattern}")
            print(f"    ├─ Length: {tbl_data['entry_length']} bytes")
            print(f"    └─ Values: {value_types}")
        
        return merged
    
    def schema_exists(self, table_name: str, schema_length: int) -> bool:
        """Zkontroluje, zda schéma již existuje"""
        for schema in self.schemas:
            if (schema['table_header'] == table_name and 
                schema['schema_length'] == schema_length):
                return True
        return False
    
    def add_schemas(self, new_schemas: Dict[str, Dict[str, Any]]) -> int:
        """Přidá nová schémata"""
        added = 0
        
        print(f"\n{'─'*60}")
        print(f"➕ Přidávám schémata...")
        
        for table_name, schema_info in new_schemas.items():
            if self.schema_exists(table_name, schema_info['schema_length']):
                print(f"  ⊝ {table_name}: Již existuje")
                continue
            
            # Vytvoř info_comment
            info_comment = schema_info.get('game_version', '')
            if schema_info.get('schema_version'):
                if info_comment:
                    info_comment += f" / {schema_info['schema_version']}"
                else:
                    info_comment = schema_info['schema_version']
            
            entry = {
                "info_comment": info_comment,
                "table_header": table_name,
                "schema_length": schema_info['schema_length'],
                "schema": {
                    "schema": schema_info['struct_pattern'],
                    "sch_len": schema_info['schema_length'],
                    "keys": schema_info['keys'],
                    "values": schema_info['value_types']
                }
            }
            
            self.schemas.append(entry)
            added += 1
            print(f"  ✓ {table_name}: PŘIDÁNO")
        
        return added
    
    def save_schemas(self, output_file: Optional[str] = None, 
                    backup: bool = True):
        """Uloží schémata do souboru"""
        if output_file is None:
            output_file = self.schema_file
        
        # Záloha
        if backup and os.path.exists(output_file):
            backup_file = output_file + '.backup'
            import shutil
            shutil.copy2(output_file, backup_file)
            print(f"\n💾 Záloha vytvořena: {backup_file}")
        
        # Ulož
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.schemas, f, indent=4, ensure_ascii=False)
        
        print(f"✓ Uloženo do: {output_file}")
        print(f"  Celkem schémat: {len(self.schemas)}")
    
    def process_files(self, json_file: str, tbl_file: str, 
                     game_version: str = "") -> int:
        """Hlavní funkce pro zpracování souborů"""
        print(f"\n{'='*60}")
        print(f"🚀 ZPRACOVÁVÁM SOUBORY")
        print(f"{'='*60}")
        print(f"JSON: {json_file}")
        print(f"TBL:  {tbl_file}")
        if game_version:
            print(f"Verze: {game_version}")
        
        # Zkontroluj existenci
        if not os.path.exists(json_file):
            print(f"✗ CHYBA: JSON soubor neexistuje")
            return 0
        
        if not os.path.exists(tbl_file):
            print(f"✗ CHYBA: TBL soubor neexistuje")
            return 0
        
        # Analyzuj a slouč
        merged = self.match_and_merge(json_file, tbl_file, game_version)
        
        # Přidej schémata
        added = self.add_schemas(merged)
        
        print(f"\n{'='*60}")
        print(f"✓ Přidáno {added} nových schémat")
        print(f"{'='*60}")
        
        return added


def main():
    print("╔" + "═"*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  ADVANCED SCHEMA ANALYZER PRO KURO DLC TABLES".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "═"*58 + "╝")
    
    analyzer = AdvancedSchemaAnalyzer('kurodlc_schema.json')
    
    if len(sys.argv) >= 3:
        # Režim příkazové řádky
        json_file = sys.argv[1]
        tbl_file = sys.argv[2]
        game_version = sys.argv[3] if len(sys.argv) > 3 else ""
        
        added = analyzer.process_files(json_file, tbl_file, game_version)
        
        if added > 0:
            save = input("\n💾 Uložit změny? (y/n): ").strip().lower()
            if save == 'y':
                analyzer.save_schemas(backup=True)
    else:
        # Interaktivní režim
        print("\n📝 Interaktivní režim")
        print("Zadejte cesty k souborům (nebo 'q' pro ukončení)\n")
        
        total_added = 0
        
        while True:
            json_file = input("JSON soubor: ").strip()
            if json_file.lower() == 'q':
                break
            
            if not json_file:
                continue
            
            tbl_file = input("TBL soubor:  ").strip()
            if not tbl_file:
                continue
            
            game_version = input("Verze hry (volitelné): ").strip()
            
            added = analyzer.process_files(json_file, tbl_file, game_version)
            total_added += added
            
            cont = input("\n➡️ Zpracovat další soubor? (y/n): ").strip().lower()
            if cont != 'y':
                break
        
        if total_added > 0:
            print(f"\n📊 Celkem přidáno: {total_added} schémat")
            save = input("💾 Uložit všechny změny? (y/n): ").strip().lower()
            if save == 'y':
                analyzer.save_schemas(backup=True)
        else:
            print("\n⊝ Žádné změny k uložení")


if __name__ == "__main__":
    main()
