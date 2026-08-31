import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.cost_x_definitions import cast_x_ceiling_line, caps_cast_x
print(cast_x_ceiling_line("X can't be greater than the number of snow lands you control."))
print(caps_cast_x("X can't be greater than the number of snow lands you control.\nfoo"))
print(cast_x_ceiling_line("X can't be greater than the number of blorps you control."))
