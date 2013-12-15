"""

A module for encoding data in the GIF format.
Built with reference to:
  http://www.w3.org/Graphics/GIF/spec-gif89a.txt
  http://en.wikipedia.org/wiki/Graphics_Interchange_Format

"""

import numpy, math
import lzw, cutils
from spec import *

def grayscaleColorTable(bits=8):
  """ Make a grayscale color table with the specified bit depth. """
  conversion = 255./(2**bits-1)
  return ''.join([3*chr(int(conversion*i)) for i in range(2**bits)])

def makeReducedColorTable(levels):
  """ Make a color table corresponding to a posterization defined in levels. """
  assert len(levels)==3
  assert levels[0]*levels[1]*levels[2]<256
  conversions = [255./(l-1) for l in levels]
  colorTable = [(int(conversions[0]*r),int(conversions[1]*g),int(conversions[2]*b))
                for r in range(levels[0]) for g in range(levels[1]) for b in range(levels[2])]
  colorTable = ''.join([chr(r)+chr(g)+chr(b) for r,g,b in colorTable])
  colorTable += chr(0)*3*(256-len(colorTable)/3)
  return colorTable

def reduceColor(channel,levels):
  """ Wraps a function from cutils to make sure the input is correct. """
  channel = channel.astype(numpy.double)
  return cutils.reduceColor(channel,levels) 
  
def reduceColorRGB(channels,levels):
  """ Posterize RGB channels and convert to color table indices. """
  data = (levels[2]*levels[1]*reduceColor(channels[0],levels[0])+
          levels[2]*reduceColor(channels[1],levels[1])+
          reduceColor(channels[2],levels[2])).astype(numpy.uint8)
  return data
  
def colorPaletteToRGB(image_data,color_table):
  """ Handles index arithmetic mapping color palette back to RGB values. """ 
  color_table_array = numpy.array([ord(c) for c in color_table])
  n_colors = color_table_array.size / 3
  color_table_array = color_table_array.reshape((n_colors,3))
  channels = [color_table_array[image_data,i] for i in range(3)]
  return channels

class GIF:
  """ The main class for reading and writing GIF files. """
  def __init__(self,shape,bitsPerColor=8,**kwargs):
    self.shape = shape
    self.globalColorTable = grayscaleColorTable(bitsPerColor)
    self.bitsPerColor = bitsPerColor
    self.graphicBlocks = []
    self.duration = kwargs.get("duration",10)
    self.repeat = kwargs.get("repeat",0)

  def addFrameFromNumpyData(self,data,colorTable=None):
    data = reduceColor(data,2**self.bitsPerColor)
    self.graphicBlocks.append(GraphicBlock(data,self.shape,bitsPerColor=self.bitsPerColor))

  def addRGBFrame(self,channels,levels=[6,7,6]):
    data = reduceColorRBG(channels,levels)
    self.bitsPerColor = 8
    self.colorTable = makeReducedColorTable(levels)
    self.graphicBlocks.append(GraphicBlock(data,self.shape))
    
  def getFrameAsRGB(self,frame_number):
    block = self.graphicBlocks[frame_number]
    imageData = block.imageData.reshape(*self.shape)
    if block.colorTable is not None:
      return colorPaletteToRGB(imageData,block.colorTable)
    else:
      return colorPaletteToRGB(imageData,self.globalColorTable)

  def save(self,filename):
    with open(filename,'wb') as f:
      f.write(HEADER)
      pf = 128+(self.bitsPerColor-1)
      LogicalScreenDescriptor(*self.shape,packed_fields=pf).toFile(f)
      f.write(self.globalColorTable)
      ApplicationExtension(self.repeat).toFile(f)
      GraphicControlExtension(self.duration).toFile(f)
      # "packed_fields":'\x08' if transparency is None else '\x09',
      # "transparent_color_index":chr(transparency) if transparency else '\x00'})
      for graphicBlock in self.graphicBlocks:
        graphicBlock.toFile(f)
      f.write(TRAILER)
      
  @staticmethod
  def fromFile(filename):
    with open(filename,'rb') as f:
      assert f.read(6)==HEADER
      lsd = LogicalScreenDescriptor.fromFile(f)
      globalColorTable = lsd.packed_fields>>7
      if globalColorTable:
        globalColorTableSize = lsd.packed_fields%8
        colorTable = f.read(3*(2**(globalColorTableSize+1)))
      g = GIF((lsd.width,lsd.height),bitsPerColor=globalColorTableSize+1)
      g.globalColorTable = colorTable
      while True:
        byte = f.read(1)
        if not byte or byte==TRAILER:
          break # Finished parsing the file.
        elif byte==ImageDescriptor.IMAGE_SEPARATOR:
          g.graphicBlocks.append(GraphicBlock.fromFile(f))
        elif byte==EXTENSION_INTRODUCER:
          label = f.read(1)
          if label == GraphicControlExtension.LABEL:
            GraphicControlExtension.fromFile(f)
          elif label==COMMENT_EXTENSION_LABEL:
            DataBlock.fromFile(f)
          elif label==ApplicationExtension.LABEL:
            ApplicationExtension.fromFile(f)
          else:
            raise Exception("Unknown label byte: %s" % ord(label))
        else:
          raise Exception("Unknown block byte: %s" % ord(byte))
    return g

class GraphicBlock:
  """ A class for graphic blocks containing an image descriptor and data. """
  def __init__(self,imageData,shape,**kwargs):
    self.imageData = imageData
    self.shape = shape
    self.colorTable = kwargs.get("colorTable",None)
    self.bitsPerColor = kwargs.get("bitsPerColor",8)
    
  def toFile(self,f):
    colorTableSize = None
    if self.colorTable:
      colorTableSize = int(math.log(len(self.colorTable)/3,2))
      packed_fields = (1<<7)+colorTableSize-1
    else:
      packed_fields = 0
    ImageDescriptor(*self.shape,packed_fields=packed_fields).toFile(f)
    if self.colorTable:
      f.write(self.colorTable)
    # table based image data
    codesize = self.bitsPerColor if colorTableSize is None else max(2,colorTableSize)
    f.write(chr(codesize))
    data = lzw.encode(self.imageData.ravel(),codeSize=codesize)
    DataBlock(data).toFile(f)
    
  @staticmethod
  def fromFile(f):
    desc = ImageDescriptor.fromFile(f)
    localColorTable = desc.packed_fields>>7
    if localColorTable:
      localColorTableSize = desc.packed_fields%8
      colorTable = f.read(3*(2**(localColorTableSize+1)))
    codeSize = ord(f.read(1))
    data = DataBlock.fromFile(f).data
    imageData = numpy.array([ord(c) for c in lzw.decode(data,codeSize)])
    return GraphicBlock(imageData,[desc.width,desc.height])

if __name__ == '__main__':
  dimensions = (200,200)
  g = GIF(dimensions,bitsPerColor=2,duration=10)
  for i in range(256):
    g.addFrameFromNumpyData(i+numpy.zeros(dimensions))
  g.save("test.gif")
  GIF.fromFile("test.gif")



