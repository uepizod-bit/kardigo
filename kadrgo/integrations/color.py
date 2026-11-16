from pathlib import Path
def config():
 import PyOpenColorIO as o
 return o.Config.CreateFromBuiltinConfig('ocio://studio-config-v2.2.0_aces-v1.3_ocio-v2.4')
def bake(r,path,size=33):
 import PyOpenColorIO as o
 c=config();t=o.DisplayViewTransform(src=r['input_space'],display=r['display'],view=r['view']);cpu=c.getProcessor(t).getDefaultCPUProcessor()
 lines=['TITLE "KADRGO OCIO bounded SDR"',f'LUT_3D_SIZE {size}','DOMAIN_MIN 0 0 0','DOMAIN_MAX 1 1 1']
 for b in range(size):
  for g in range(size):
   for red in range(size):lines.append(' '.join(f'{max(0,min(1,float(x))):.8f}' for x in cpu.applyRGB([red/(size-1),g/(size-1),b/(size-1)])))
 Path(path).write_text('\n'.join(lines)+'\n');return path
