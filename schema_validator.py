#!/usr/bin/env python3
"""
Schema Validator
Ověřuje a porovnává schémata v kurodlc_schema.json

GitHub eArmada8/kuro_dlc_tool
"""

import json
import struct
import sys
from collections import defaultdict


def load_schemas(schema_file='kurodlc_schema.json'):
    """Načte schémata ze souboru"""
    try:
        with open(schema_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"✗ Soubor {schema_file} neexistuje!")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Chyba při čtení JSON: {e}")
        sys.exit(1)


def validate_schema(schema_entry, index):
    """Validuje jednotlivé schéma"""
    errors = []
    warnings = []
    
    # Kontrola povinných polí
    required_fields = ['table_header', 'schema_length', 'schema']
    for field in required_fields:
        if field not in schema_entry:
            errors.append(f"Chybí pole: {field}")
    
    if errors:
        return errors, warnings
    
    # Kontrola schema objektu
    schema = schema_entry['schema']
    required_schema_fields = ['schema', 'sch_len', 'keys', 'values']
    for field in required_schema_fields:
        if field not in schema:
            errors.append(f"Chybí pole schema.{field}")
    
    if errors:
        return errors, warnings
    
    # Kontrola konzistence délek
    if schema_entry['schema_length'] != schema['sch_len']:
        errors.append(f"Neshoduje se schema_length ({schema_entry['schema_length']}) != sch_len ({schema['sch_len']})")
    
    # Kontrola struct pattern
    try:
        calculated_size = struct.calcsize(schema['schema'])
        if calculated_size != schema['sch_len']:
            errors.append(f"Struct pattern '{schema['schema']}' má velikost {calculated_size}, ale sch_len je {schema['sch_len']}")
    except struct.error as e:
        errors.append(f"Neplatný struct pattern: {e}")
    
    # Kontrola konzistence keys a values
    if len(schema['keys']) != len(schema['values']):
        errors.append(f"Počet keys ({len(schema['keys'])}) != počet values ({len(schema['values'])})")
    
    # Kontrola typů v values
    valid_types = set('ntab')
    for i, vtype in enumerate(schema['values']):
        if vtype not in valid_types:
            warnings.append(f"Neznámý typ hodnoty '{vtype}' na pozici {i}")
    
    # Kontrola duplicitních klíčů
    if len(schema['keys']) != len(set(schema['keys'])):
        duplicates = [k for k in schema['keys'] if schema['keys'].count(k) > 1]
        errors.append(f"Duplicitní klíče: {set(duplicates)}")
    
    return errors, warnings


def find_duplicates(schemas):
    """Najde duplicitní schémata"""
    schema_map = defaultdict(list)
    
    for i, schema in enumerate(schemas):
        key = (schema['table_header'], schema['schema_length'])
        schema_map[key].append(i)
    
    duplicates = {k: v for k, v in schema_map.items() if len(v) > 1}
    return duplicates


def compare_schemas(schema1, schema2):
    """Porovná dvě schémata a vypíše rozdíly"""
    differences = []
    
    # Porovnej struct pattern
    if schema1['schema']['schema'] != schema2['schema']['schema']:
        differences.append(f"Pattern: '{schema1['schema']['schema']}' vs '{schema2['schema']['schema']}'")
    
    # Porovnej keys
    keys1 = schema1['schema']['keys']
    keys2 = schema2['schema']['keys']
    if keys1 != keys2:
        if len(keys1) != len(keys2):
            differences.append(f"Počet keys: {len(keys1)} vs {len(keys2)}")
        else:
            for i, (k1, k2) in enumerate(zip(keys1, keys2)):
                if k1 != k2:
                    differences.append(f"Key[{i}]: '{k1}' vs '{k2}'")
    
    # Porovnej values
    if schema1['schema']['values'] != schema2['schema']['values']:
        differences.append(f"Values: '{schema1['schema']['values']}' vs '{schema2['schema']['values']}'")
    
    return differences


def main():
    print("╔" + "═"*58 + "╗")
    print("║" + "  SCHEMA VALIDATOR".center(58) + "║")
    print("╚" + "═"*58 + "╝\n")
    
    # Načti schémata
    schema_file = sys.argv[1] if len(sys.argv) > 1 else 'kurodlc_schema.json'
    schemas = load_schemas(schema_file)
    
    print(f"📊 Načteno schémat: {len(schemas)}\n")
    
    # Validace
    print("🔍 Validuji schémata...\n")
    total_errors = 0
    total_warnings = 0
    
    for i, schema in enumerate(schemas):
        errors, warnings = validate_schema(schema, i)
        
        if errors or warnings:
            print(f"┌─ Schéma #{i}: {schema.get('table_header', 'N/A')} "
                  f"(délka: {schema.get('schema_length', 'N/A')})")
            print(f"│  Info: {schema.get('info_comment', 'N/A')}")
            
            for error in errors:
                print(f"│  ✗ CHYBA: {error}")
                total_errors += 1
            
            for warning in warnings:
                print(f"│  ⚠ VAROVÁNÍ: {warning}")
                total_warnings += 1
            
            print()
    
    if total_errors == 0 and total_warnings == 0:
        print("✓ Všechna schémata jsou validní!\n")
    else:
        print(f"{'─'*60}")
        print(f"Celkem chyb: {total_errors}")
        print(f"Celkem varování: {total_warnings}\n")
    
    # Hledání duplicit
    print("🔍 Hledám duplicitní schémata...\n")
    duplicates = find_duplicates(schemas)
    
    if duplicates:
        print(f"⚠ Nalezeno {len(duplicates)} duplicitních schémat:\n")
        
        for (table_name, schema_length), indices in duplicates.items():
            print(f"┌─ {table_name} (délka: {schema_length})")
            print(f"│  Nalezeno na pozicích: {indices}")
            
            # Porovnej rozdíly
            for i in range(1, len(indices)):
                diffs = compare_schemas(schemas[indices[0]], schemas[indices[i]])
                if diffs:
                    print(f"│  Rozdíly mezi #{indices[0]} a #{indices[i]}:")
                    for diff in diffs:
                        print(f"│    • {diff}")
            print()
    else:
        print("✓ Žádné duplicity!\n")
    
    # Statistiky
    print("📈 Statistiky:\n")
    
    # Podle verze hry
    by_version = defaultdict(int)
    for schema in schemas:
        version = schema.get('info_comment', 'Unknown')
        by_version[version] += 1
    
    print("Podle verze:")
    for version, count in sorted(by_version.items()):
        print(f"  {version:30s}: {count:3d}")
    
    print()
    
    # Podle tabulky
    by_table = defaultdict(int)
    for schema in schemas:
        table = schema.get('table_header', 'Unknown')
        by_table[table] += 1
    
    print(f"Unikátních tabulek: {len(by_table)}")
    
    # Tabulky s více verzemi
    multi_version = {k: v for k, v in by_table.items() if v > 1}
    if multi_version:
        print(f"\nTabulky s více verzemi:")
        for table, count in sorted(multi_version.items(), key=lambda x: x[1], reverse=True):
            print(f"  {table:30s}: {count:3d} verzí")
    
    print()
    
    # Souhrn
    print("═"*60)
    if total_errors == 0:
        print("✓ Validace úspěšná!")
    else:
        print(f"✗ Nalezeno {total_errors} chyb")


if __name__ == "__main__":
    main()
