# -*- coding: utf-8 -*-
"""Small deterministic, offline glTF 2.0 PBR props and SVG overview maps.

Both outputs are text files for explicit review and import in Roblox Studio.
No external meshes, textures, libraries or network access. The resulting
meshes have normal attributes, indexed geometry and simple procedural
color/roughness textures; they are not hand-sculpted production assets.
"""
from __future__ import annotations
import base64
import html
import json
import math
import random
import struct
import zlib

COLORS = {
    "wood": ((117, 78, 48), 0.0, .86),
    "leaves": ((46, 116, 67), 0.0, .94),
    "stone": ((144, 149, 153), 0.02, .83),
    "plaster": ((220, 200, 168), 0.0, .9),
    "roof": ((67, 88, 110), .06, .72),
    "glass": ((75, 156, 194), .1, .24),
    "metal": ((159, 169, 174), .85, .34),
    "paint": ((203, 52, 45), .56, .38),
    "rubber": ((31, 34, 38), .0, .95),
    "neon": ((48, 203, 234), .12, .27),
    "sand": ((201, 162, 113), .01, .91),
}
SHAPES = frozenset({"box", "cylinder", "sphere", "cone"})


def _png_rgba(pixels, width=32, height=32):
    if len(pixels) != width*height*4:
        raise ValueError("Incorrect RGBA pixel buffer")
    def chunk(tag, content):
        return (struct.pack(">I", len(content))+tag+content+
                struct.pack(">I", zlib.crc32(tag+content)&0xffffffff))
    rows=b"".join(b"\x00"+pixels[y*width*4:(y+1)*width*4]
                  for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,6,0,0,0))+
            chunk(b"IDAT",zlib.compress(rows,9))+
            chunk(b"IEND",b""))


def _texture(color,metallic,roughness,seed,kind):
    rng=random.Random(seed)
    rgb=bytearray()
    mr=bytearray()
    for y in range(32):
        for x in range(32):
            band=2.8*math.sin(y*.92) if kind=="wood" else 0
            grain=band+rng.uniform(-9,9)
            if kind in ("glass","neon"):
                grain*=.25
            rgb.extend([max(0,min(255,int(v+grain))) for v in color]+[255])
            mr.extend((255,round(roughness*255),round(metallic*255),255))
    return _png_rgba(rgb),_png_rgba(mr)


def _geometry(shape,segments=16):
    """Right-handed indexed unit mesh with UVs and explicit vertex normals."""
    vertices=[]; normals=[]; uvs=[]; triangles=[]
    def vert(p,n,uv):
        vertices.append(p);normals.append(n);uvs.append(uv)
        return len(vertices)-1
    if shape=="box":
        faces=[
            ((1,0,0),(0,0,-1),(0,1,0)),
            ((-1,0,0),(0,0,1),(0,1,0)),
            ((0,1,0),(1,0,0),(0,0,-1)),
            ((0,-1,0),(1,0,0),(0,0,1)),
            ((0,0,1),(1,0,0),(0,1,0)),
            ((0,0,-1),(-1,0,0),(0,1,0)),
        ]
        for normal,u,v in faces:
            start=len(vertices)
            for a,b,uv in ((-1,-1,(0,0)),(1,-1,(1,0)),
                           (1,1,(1,1)),(-1,1,(0,1))):
                p=tuple(normal[i]*.5 + u[i]*a*.5+v[i]*b*.5 for i in range(3))
                vert(p,normal,uv)
            triangles.extend((start,start+1,start+2,start,start+2,start+3))
    elif shape in ("cylinder","cone"):
        for i in range(segments):
            a=2*math.pi*i/segments
            b=2*math.pi*(i+1)/segments
            ca,sa=math.cos(a),math.sin(a)
            cb,sb=math.cos(b),math.sin(b)
            if shape=="cylinder":
                start=len(vertices)
                for pos,n,uv in (
                    ((.5*ca,-.5,.5*sa),(ca,0,sa),(i/segments,0)),
                    ((.5*ca,.5,.5*sa),(ca,0,sa),(i/segments,1)),
                    ((.5*cb,.5,.5*sb),(cb,0,sb),((i+1)/segments,1)),
                    ((.5*cb,-.5,.5*sb),(cb,0,sb),((i+1)/segments,0))):
                    vert(pos,n,uv)
                triangles.extend((start,start+1,start+2,start,start+2,start+3))
                p=len(vertices)
                vert((0,.5,0),(0,1,0),(.5,.5))
                vert((.5*cb,.5,.5*sb),(0,1,0),(.5+.5*cb,.5+.5*sb))
                vert((.5*ca,.5,.5*sa),(0,1,0),(.5+.5*ca,.5+.5*sa))
                triangles.extend((p,p+1,p+2))
            else:
                start=len(vertices)
                # cone normal: horizontal radial with upward component
                for angle,yy,uv in ((a,-.5,(i/segments,0)),
                                    (a,.5,(i/segments,1)),
                                    (b,-.5,((i+1)/segments,0))):
                    rad=0 if yy>.49 else .5
                    normal=(math.cos(angle)*.8944,.4472,math.sin(angle)*.8944)
                    vert((rad*math.cos(angle),yy,rad*math.sin(angle)),normal,uv)
                triangles.extend((start,start+1,start+2))
            p=len(vertices)
            vert((0,-.5,0),(0,-1,0),(.5,.5))
            vert((.5*ca,-.5,.5*sa),(0,-1,0),(.5+.5*ca,.5+.5*sa))
            vert((.5*cb,-.5,.5*sb),(0,-1,0),(.5+.5*cb,.5+.5*sb))
            triangles.extend((p,p+1,p+2))
    elif shape=="sphere":
        for i in range(9):
            phi=math.pi*i/8
            for j in range(17):
                theta=math.pi*2*j/16
                v=(math.sin(phi)*math.cos(theta),math.cos(phi),
                   math.sin(phi)*math.sin(theta))
                vert(tuple(.5*x for x in v),v,(j/16,i/8))
        for i in range(8):
            for j in range(16):
                a=i*17+j
                b=a+17
                triangles.extend((a,a+1,b,a+1,b+1,b))
    else:
        raise ValueError("Unknown mesh shape")
    if not triangles or len(vertices)>65535:
        raise ValueError("Mesh vertex limit exceeded")
    return vertices,normals,uvs,triangles


class _GLTF:
    def __init__(self,name,seed):
        self.name=name
        self.seed=seed
        self.bin=bytearray()
        self.views=[]
        self.accessors=[]
        self.meshes=[]
        self.nodes=[]
        self.materials=[]
        self.images=[]
        self.textures=[]
        self.mesh_cache={}
        self.material_map={}
    def _accessor(self,values,kind,component,target,components):
        while len(self.bin)%4:self.bin.append(0)
        offset=len(self.bin)
        fmt="f" if component==5126 else "H"
        flat=[value for row in values
              for value in (row if isinstance(row,(list,tuple)) else (row,))]
        self.bin.extend(struct.pack("<"+fmt*len(flat),*flat))
        vi=len(self.views)
        self.views.append({"buffer":0,"byteOffset":offset,
                           "byteLength":len(self.bin)-offset,"target":target})
        obj={"bufferView":vi,"componentType":component,
             "count":len(values),"type":kind}
        if kind=="VEC3" and component==5126:
            obj["min"]=[min(v[i] for v in values) for i in range(3)]
            obj["max"]=[max(v[i] for v in values) for i in range(3)]
        self.accessors.append(obj)
        return len(self.accessors)-1
    def _image(self,data):
        self.images.append({"uri":"data:image/png;base64,"+
                            base64.b64encode(data).decode("ascii")})
        tex=len(self.textures)
        self.textures.append({"source":len(self.images)-1})
        return tex
    def material(self,kind):
        if kind in self.material_map:return self.material_map[kind]
        color,metal,rough=COLORS[kind]
        diffuse,metal_rough=_texture(
            color,metal,rough,self.seed+len(self.materials)*17,kind)
        idx=len(self.materials)
        base=self._image(diffuse)
        mr=self._image(metal_rough)
        mat={"name":kind,"pbrMetallicRoughness":{
            "baseColorFactor":[1,1,1,1],"baseColorTexture":{"index":base},
            "metallicRoughnessTexture":{"index":mr},
            "metallicFactor":metal,"roughnessFactor":rough},
            "doubleSided":False}
        if kind=="neon":
            mat["emissiveFactor"]=[.08,.62,.82]
        self.materials.append(mat)
        self.material_map[kind]=idx
        return idx
    def mesh(self,shape,material):
        key=(shape,material)
        if key in self.mesh_cache:return self.mesh_cache[key]
        coords,normals,uvs,indices=_geometry(shape)
        position=self._accessor(coords,"VEC3",5126,34962,3)
        normal=self._accessor(normals,"VEC3",5126,34962,3)
        tex=self._accessor(uvs,"VEC2",5126,34962,2)
        faces=self._accessor(indices,"SCALAR",5123,34963,1)
        mesh_idx=len(self.meshes)
        self.meshes.append({"name":shape+"_"+material,
            "primitives":[{"attributes":{"POSITION":position,"NORMAL":normal,
                                          "TEXCOORD_0":tex},
                           "indices":faces,"material":self.material(material),
                           "mode":4}]})
        self.mesh_cache[key]=mesh_idx
        return mesh_idx
    def add(self,label,shape,material,pos,size,rotation=None):
        if len(self.nodes)>300:
            raise ValueError("Too many GLTF nodes")
        node={"name":label,"mesh":self.mesh(shape,material),
              "translation":[float(v) for v in pos],
              "scale":[float(v) for v in size]}
        if rotation is not None:node["rotation"]=rotation
        self.nodes.append(node)
    def finish(self):
        binary=base64.b64encode(bytes(self.bin)).decode("ascii")
        scene={"asset":{"version":"2.0","generator":"JARVIS NOVA PBR mesh export"},
            "scene":0,"scenes":[{"name":self.name,"nodes":list(range(len(self.nodes)))}],
            "nodes":self.nodes,"meshes":self.meshes,"materials":self.materials,
            "textures":self.textures,"images":self.images,"accessors":self.accessors,
            "bufferViews":self.views,"buffers":[{"byteLength":len(self.bin),
                "uri":"data:application/octet-stream;base64,"+binary}]}
        return json.dumps(scene,separators=(",",":"),ensure_ascii=False)


def export_prop_gltf(name,kind,seed=8472,detail="detailed"):
    """Return a self-contained glTF file; never uses network resources."""
    from roblox_world_builder import MODELS
    if kind not in MODELS or detail not in ("balanced","detailed"):
        raise ValueError("Invalid prop kind/detail")
    if not isinstance(name,str) or not name.isascii() or not name.replace("_","").isalnum():
        raise ValueError("Invalid model name")
    if type(seed) is not int or not 0<=seed<=1_000_000:
        raise ValueError("Invalid seed")
    g=_GLTF(name,seed)
    def add(label,shape,mat,p,scale,angle=None):
        quat=None
        if angle is not None:
            quat=[0,0,math.sin(angle/2),math.cos(angle/2)]
        g.add(label,shape,mat,p,scale,quat)
    if kind=="tree":
        add("Trunk","cylinder","wood",(0,3,0),(1.7,6,1.7))
        for i in range(7 if detail=="detailed" else 4):
            theta=2*math.pi*i/7
            add("Canopy_%d"%i,"sphere","leaves",
                (2.1*math.cos(theta),7.2+(i%3)*.8,2.1*math.sin(theta)),
                (4.7,3.8,4.7))
        add("Crown","cone","leaves",(0,9.2,0),(6,5,6))
    elif kind=="house":
        add("Foundation","box","stone",(0,.4,0),(11,.8,9))
        add("Walls","box","plaster",(0,4,0),(10,7,8))
        for i,side in enumerate((-1,1)):
            add("RoofSlope%d"%i,"box","roof",(side*2.65,8.25,0),
                (6.5,.65,9.1),side*.38)
            for z in (-2.3,2.3):
                add("WindowFrame%d_%d"%(i,int(z>0)),
                    "box","wood",(side*5.15,4,z),(.3,2.5,2.8))
                add("WindowGlass%d_%d"%(i,int(z>0)),
                    "box","glass",(side*5.36,4,z),(.12,2.1,2.4))
        add("Door","box","wood",(0,2,-4.06),(2.1,3.5,.25))
        add("DoorHandle","sphere","metal",(.76,2,-4.24),(.28,.28,.28))
        add("Chimney","box","stone",(2.6,9.2,1.5),(1.4,3.4,1.4))
    elif kind=="castle":
        add("Keep","box","stone",(0,10,0),(14,20,14))
        add("KeepRoof","cone","roof",(0,22,0),(16,8,16))
        for i,x in enumerate((-10,10)):
            for j,z in enumerate((-10,10)):
                add("Tower_%d_%d"%(i,j),"cylinder","stone",
                    (x,11,z),(7,22,7))
                add("TowerRoof_%d_%d"%(i,j),"cone","roof",
                    (x,24.5,z),(8,8,8))
                for a in range(4):
                    theta=2*math.pi*a/4
                    add("Merlon_%d_%d_%d"%(i,j,a),"box","stone",
                        (x+2.6*math.cos(theta),22.5,
                         z+2.6*math.sin(theta)),(2,2.5,2))
        add("Gate","box","wood",(0,3,-7.15),(4.5,6,.4))
    elif kind=="sports_car":
        add("VehicleBody","box","paint",(0,1.6,0),(4.6,1.8,9))
        add("Cabin","box","glass",(0,3.2,1.1),(3.9,1.7,4.2))
        add("Hood","box","paint",(0,2.2,-3),(4.5,.6,3.1))
        add("Spoiler","box","metal",(0,2.8,4.2),(4.7,.25,1))
        for i,x in enumerate((-2.4,2.4)):
            for j,z in enumerate((-3.1,3.1)):
                add("Wheel_%d_%d"%(i,j),"cylinder","rubber",
                    (x,.8,z),(1.35,.8,1.35))
                add("Hub_%d_%d"%(i,j),"cylinder","metal",
                    (x+(.46 if x>0 else -.46),.8,z),(.75,.12,.75))
        for x in (-1.4,1.4):
            add("Headlight","box","glass",(x,1.85,-4.56),(1,.4,.16))
    elif kind=="sci_fi_portal":
        add("Platform","cylinder","stone",(0,.25,0),(12,.5,9))
        for i in range(24 if detail=="detailed" else 12):
            theta=i*2*math.pi/(24 if detail=="detailed" else 12)
            x=4*math.cos(theta);y=5+4*math.sin(theta)
            add("EnergyRing_%02d"%i,"box","neon",(x,y,0),
                (1.45,.9,1.2),theta+math.pi/2)
        add("Console","box","metal",(0,1.2,5),(2,2,1.6))
    else:
        rng=random.Random(seed)
        for i in range(8 if detail=="detailed" else 4):
            x=rng.uniform(-3,3);z=rng.uniform(-3,3)
            add("Boulder_%02d"%i,"sphere","stone",
                (x,rng.uniform(.6,1.4),z),
                (rng.uniform(1.5,3.7),rng.uniform(1.1,2.7),
                 rng.uniform(1.4,3.5)))
    return g.finish()


def make_map_svg(theme,size=384,seed=8472):
    """Top-down design overview; not a literal render of Roblox Terrain."""
    from roblox_world_builder import THEMES,SIZES
    if theme not in THEMES or size not in SIZES or type(seed) is not int or not 0<=seed<=1_000_000:
        raise ValueError("Invalid map overview settings")
    rng=random.Random(seed)
    city=theme in ("city","cyberpunk")
    bg={"forest":"#355c43","island":"#2c81a4","mountains":"#77868e",
        "city":"#7b8389","cyberpunk":"#222b4c","desert":"#d2b073"}[theme]
    forest="#2c7655"; road="#33434b" if theme!="cyberpunk" else "#30264e"
    items=['<svg xmlns="http://www.w3.org/2000/svg" width="840" height="900" viewBox="0 0 840 900">',
        '<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="'+bg+
        '"/><stop offset="1" stop-color="#101c30"/></linearGradient>',
        '<filter id="shadow"><feDropShadow dx="1" dy="3" stdDeviation="3" flood-opacity=".25"/></filter></defs>',
        '<rect width="840" height="900" fill="#101b2a"/>',
        '<rect x="42" y="110" width="756" height="690" rx="20" fill="url(#bg)" stroke="#a9c2ca" stroke-width="3"/>']
    if theme=="island":
        items.append('<ellipse cx="420" cy="452" rx="335" ry="292" fill="#d9c58d"/>')
        items.append('<ellipse cx="420" cy="455" rx="290" ry="252" fill="#509468"/>')
    if city:
        for x in range(105,790,116):
            items.append(f'<path d="M{x} 140 V770" stroke="{road}" stroke-width="23"/>')
        for y in range(173,790,120):
            items.append(f'<path d="M70 {y} H772" stroke="{road}" stroke-width="23"/>')
        for x in range(85,738,116):
            for y in range(198,736,120):
                w=rng.randint(35,62);h=rng.randint(38,70)
                c=("#6088a4" if theme=="city" else rng.choice(("#3c75a5","#6659a8","#38a1b7")))
                items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{c}" stroke="#d1dee7" stroke-width="2"/>')
                items.append(f'<rect x="{x+6}" y="{y+7}" width="{max(6,w-12)}" height="7" fill="#dbe5b8" opacity=".45"/>')
    else:
        for i in range(95 if theme=="forest" else 63):
            x=rng.randint(96,739);y=rng.randint(160,743)
            if theme=="island" and ((x-420)/330)**2+((y-452)/284)**2>1:
                continue
            r=rng.randint(7,23)
            if theme=="mountains":
                items.append(f'<path d="M{x-r} {y+r} L{x} {y-r*2} L{x+r} {y+r} Z" fill="#b9c3c7" stroke="#5c6d76" stroke-width="2"/>')
            elif theme=="desert":
                items.append(f'<path d="M{x-r} {y} Q{x} {y-r} {x+r} {y+3}" stroke="#b97d50" stroke-width="3" fill="none" opacity=".65"/>')
            else:
                items.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{forest if i%3 else "#68aa70"}" stroke="#d2d8b0" stroke-opacity=".4"/>')
        if theme!="island":
            items.append('<path d="M75 570 C210 360 300 640 445 420 S690 320 767 170" stroke="#d6c79f" stroke-width="16" opacity=".8" fill="none"/>')
    items.extend([
        '<circle cx="420" cy="456" r="15" fill="#fff2be" stroke="#213b5d" stroke-width="4"/>',
        '<path d="M420 428 V482 M394 456 H446" stroke="#243c55" stroke-width="2"/>',
        '<rect x="42" y="28" width="756" height="66" rx="11" fill="#192c41"/>',
        '<text x="66" y="68" font-family="Arial" font-size="25" fill="#f3f5f3">JARVIS NOVA | '+html.escape(theme.upper())+' | '+str(size)+' STUDS</text>',
        '<text x="74" y="842" font-family="Arial" font-size="17" fill="#e1eff1">TOP-DOWN DESIGN CONCEPT - NOT A TERRAIN HEIGHTMAP</text>',
        '<text x="694" y="843" font-family="Arial" font-size="17" fill="#9ce4df">N  ↑</text>',
        '</svg>'])
    return "\n".join(items)
