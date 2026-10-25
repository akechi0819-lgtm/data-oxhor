import unittest
from dashboard_product.management.heads import qualified_students

class GuanyuanHeadsTest(unittest.TestCase):
    def row(self,student,course,amount,signup=1):
        return dict(student_id=student,class_code=course,value=amount,registration_count=signup)
    def test_class_threshold_zero_signup_rows_and_negative_amount(self):
        r=self.row
        rows=[r('split','a',800),r('split','b',800),r('joined','a',800),r('joined','a',700),
              r('zero_registration','a',2000,0),r('zero_registration','a',0,1),
              r('negative','a',-1500),r('below','a',1499.99),r('no_signup','a',2000,0),
              r('offset','a',2000),r('offset','a',-600),r('joined','b',2000)]
        self.assertEqual(qualified_students(rows),{'joined','zero_registration','negative'})
    def test_combined_scope_recomputes_qualification(self):
        active=[self.row('cross','class',800),self.row('overlap','class',2000)]
        passive=[self.row('cross','class',700),self.row('overlap','class',2000)]
        self.assertEqual(qualified_students(active),{'overlap'})
        self.assertEqual(qualified_students(passive),{'overlap'})
        self.assertEqual(qualified_students(active+passive),{'overlap','cross'})
