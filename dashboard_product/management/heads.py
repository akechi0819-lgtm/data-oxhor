"""观远语培报名人头：筛选后按学员/班级金额门槛，最终学员去重。"""
from collections import defaultdict
from decimal import Decimal

def qualified_students(records):
    amounts=defaultdict(Decimal)
    enrolled=set()
    for row in records:
        student=str(row.get('student_id') or '').strip()
        if not student: continue
        key=(student,row.get('class_code'))
        amounts[key]+=Decimal(str(row.get('value') or 0))
        if Decimal(str(row.get('registration_count') or 0))>0:
            enrolled.add(key)
    return {student for student,course in enrolled if abs(amounts[(student,course)])>=1500}
