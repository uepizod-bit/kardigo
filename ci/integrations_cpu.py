"""All integration checks except OpenGL: hosted Windows runners lack a guaranteed GL 3.3 GPU."""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_integrations import Tests
suite=unittest.TestSuite(Tests(name) for name in unittest.defaultTestLoader.getTestCaseNames(Tests) if name!='test_gl_video')
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
