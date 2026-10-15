"""Select GDI classes for isolated API tests without running application startup."""
import ast

def drawing_classes(source, keep):
    classes = [n for n in ast.parse(source).body
               if isinstance(n, ast.ClassDef) and n.name in ('GDIDrawingSurface', 'GDIWindow')]
    for cls in classes:
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in keep]
        if not cls.body:
            cls.body = [ast.Pass(lineno=cls.lineno, col_offset=4)]
    return classes
