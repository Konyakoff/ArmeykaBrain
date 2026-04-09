import json
import os
import glob

def load_gemini_models() -> list:
    path = os.path.join("data", "gemini_models.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def load_json_db() -> dict:
    """
    Загружает все JSON-файлы из папки data/Zakony_json/
    и возвращает словарь формата:
    {
      "название_файла_без_расширения": {
        "номер_статьи_или_пункта": "rag_context"
      }
    }
    """
    db_dict = {}
    json_dir = os.path.join("data", "Zakony_json")
    
    if not os.path.exists(json_dir):
        return db_dict
        
    for file_path in glob.glob(os.path.join(json_dir, "*.json")):
        file_name = os.path.basename(file_path)
        base_name = os.path.splitext(file_name)[0]
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                file_dict = {
                    "by_number": {},
                    "by_id": {}
                }
                for item in data:
                    item_number = item.get("number")
                    context = item.get("rag_context")
                    parent_id = item.get("parent_id")
                    item_id = item.get("id")
                    section = item.get("section")
                    subsection = item.get("subsection")
                    
                    if context and item_id:
                        # Сохраняем по id для точного поиска
                        file_dict["by_id"][item_id] = {
                            "context": context,
                            "id": item_id,
                            "section": section,
                            "subsection": subsection
                        }
                        
                        # Сохраняем по номеру (только для родительских статей) для обратной совместимости
                        if item_number and parent_id is None:
                            num_str = str(item_number)
                            if num_str not in file_dict["by_number"]:
                                file_dict["by_number"][num_str] = []
                            file_dict["by_number"][num_str].append({
                                "context": context,
                                "id": item_id,
                                "section": section,
                                "subsection": subsection
                            })
                        
                db_dict[base_name] = file_dict
            except Exception as e:
                print(f"Ошибка загрузки {file_path}: {e}")
                
    return db_dict

def find_rag_context(file_name: str, item_number: str, section: str = "", subsection: str = "") -> list:
    """
    Умный скрипт поиска rag_context по имени файла, номеру статьи/пункта и (опционально) разделу/подразделу.
    Возвращает список словарей [{"context": "...", "id": "..."}, ...] или пустой список.
    """
    if file_name not in JSON_DB:
        return []
        
    db_file = JSON_DB[file_name]
    num_str = str(item_number)
    
    if num_str not in db_file.get("by_number", {}):
        return []
        
    matches = db_file["by_number"][num_str]
    
    # Если Gemini не вернул раздел/подраздел или нашлось только одно совпадение
    if len(matches) == 1 or (not section and not subsection):
        return matches
        
    # Пытаемся отфильтровать по section и subsection (учитываем неточности парсинга)
    filtered = []
    for match in matches:
        match_section = str(match.get("section") or "").strip().lower()
        match_subsection = str(match.get("subsection") or "").strip().lower()
        target_section = section.lower()
        target_subsection = subsection.lower()
        
        # Проверяем, есть ли вхождения нужных строк
        sec_ok = not section or (target_section in match_section or match_section in target_section)
        subsec_ok = not subsection or (target_subsection in match_subsection or match_subsection in target_subsection)
        
        if sec_ok and subsec_ok:
            filtered.append(match)
            
    # Если фильтрация слишком строгая и ничего не оставила, возвращаем все варианты с этим номером
    return filtered if filtered else matches

# Предзагрузка данных при импорте модуля
GEMINI_MODELS = load_gemini_models()
JSON_DB = load_json_db()
