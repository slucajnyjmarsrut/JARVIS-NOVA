# -*- coding: utf-8 -*-
"""Generate bounded, editable Roblox Studio landscapes and 3D prop models.

Writes Luau for Studio Command Bar; never silently opens Roblox, deletes
existing places, fetches assets or publishes anything. All objects remain
editable after the Command Bar operation completes.
"""
from __future__ import annotations
import json
import re
from code_workspace import ChangePlan, ProposedFile, WorkspaceError, validate_plan

THEMES=("forest","island","mountains","city","cyberpunk","desert")
MODELS=("tree","house","castle","sports_car","sci_fi_portal","rocks")
SIZES=(192,256,384,512)
QUALITIES=("balanced","detailed")

_COMMON=r'''
-- JARVIS NOVA: paste the entire file into Roblox Studio > View > Command Bar.
local Workspace=game:GetService("Workspace")
local Lighting=game:GetService("Lighting")
local Terrain=Workspace.Terrain
local rng=Random.new(SEED)
local world=Instance.new("Model")
world.Name="JARVIS_NOVA_"..NAME
world.Parent=Workspace
local count=0
local MAX_PARTS=(QUALITY=="detailed") and 3400 or 1400
local function rgb(r,g,b) return Color3.fromRGB(r,g,b) end
local function part(parent,label,size,cf,color,mat,shape)
    if count>=MAX_PARTS then return nil end
    local p=Instance.new("Part")
    p.Name=label
    p.Anchored=true
    p.Size=size
    p.CFrame=cf
    p.Color=color
    p.Material=mat or Enum.Material.SmoothPlastic
    if shape then p.Shape=shape end
    p.TopSurface=Enum.SurfaceType.Smooth
    p.BottomSurface=Enum.SurfaceType.Smooth
    p.CastShadow=true
    p.Parent=parent
    count+=1
    return p
end
local function group(name)
    local m=Instance.new("Model")
    m.Name=name
    m.Parent=world
    return m
end
local function tree(x,y,z,s)
    local m=group("DetailedTree")
    part(m,"Bark",Vector3.new(2*s,9*s,2*s),CFrame.new(x,y+4.5*s,z),
        rgb(92,65,45),Enum.Material.Wood,Enum.PartType.Cylinder)
    for i=1,5 do
        local a=i*math.pi*2/5
        part(m,"Foliage",Vector3.new(7*s,4.5*s,7*s),
            CFrame.new(x+math.cos(a)*2*s,y+(10+i%2)*s,z+math.sin(a)*2*s),
            rgb(43+i*4,107+i*5,64+i*3),Enum.Material.Grass,Enum.PartType.Ball)
    end
end
local function rock(x,y,z,s)
    local m=group("RockFormation")
    for i=1,4 do
        part(m,"Rock",Vector3.new(s*(1+i*.13),s*.75,s*.9),
            CFrame.new(x+rng:NextNumber(-s/3,s/3),y+s*.35,
                z+rng:NextNumber(-s/3,s/3))
                *CFrame.Angles(0,rng:NextNumber(0,6),.12*i),
            rgb(107+i*4,110+i*4,108+i*4),
            Enum.Material.Slate,Enum.PartType.Ball)
    end
end
local function house(x,y,z,s)
    local m=group("ArchitecturalHouse")
    part(m,"Foundation",Vector3.new(20*s,2*s,17*s),
        CFrame.new(x,y+s,z),rgb(126,119,112),Enum.Material.Concrete)
    part(m,"Walls",Vector3.new(18*s,12*s,15*s),
        CFrame.new(x,y+8*s,z),rgb(212,194,169),Enum.Material.Plaster)
    for side=-1,1,2 do
        part(m,"SlopedRoof",Vector3.new(12*s,1*s,17*s),
            CFrame.new(x+side*4.5*s,y+15.9*s,z)
            *CFrame.Angles(0,0,-side*.35),
            rgb(79,89,109),Enum.Material.Slate)
        for floor=1,2 do
            part(m,"Window",Vector3.new(.3*s,3.3*s,3.8*s),
                CFrame.new(x+side*9.2*s,y+(4+floor*3.6)*s,z-3*s),
                rgb(97,166,194),Enum.Material.Glass)
        end
    end
    part(m,"Door",Vector3.new(3*s,6*s,.35*s),
        CFrame.new(x,y+4*s,z-7.7*s),rgb(99,65,49),Enum.Material.Wood)
end
local function castle(x,y,z,s)
    local m=group("Castle")
    part(m,"Keep",Vector3.new(19*s,28*s,19*s),CFrame.new(x,y+14*s,z),
        rgb(157,153,141),Enum.Material.Cobblestone)
    for dx=-1,1,2 do for dz=-1,1,2 do
        local xx=x+12*dx*s
        local zz=z+12*dz*s
        part(m,"Tower",Vector3.new(9*s,34*s,9*s),
            CFrame.new(xx,y+17*s,zz),rgb(135,135,138),
            Enum.Material.Rock,Enum.PartType.Cylinder)
        for i=1,8 do
            local a=math.pi*2*i/8
            part(m,"Merlon",Vector3.new(2*s,3*s,2*s),
                CFrame.new(xx+math.cos(a)*3.5*s,y+35*s,
                    zz+math.sin(a)*3.5*s),
                rgb(156,153,146),Enum.Material.Rock)
        end
    end end
    part(m,"Gate",Vector3.new(6*s,10*s,.4*s),
        CFrame.new(x,y+5*s,z-9.7*s),rgb(69,55,43),Enum.Material.Wood)
end
local function sportscar(x,y,z,s)
    local m=group("SportsCar")
    part(m,"Body",Vector3.new(8*s,2.1*s,17*s),
        CFrame.new(x,y+3*s,z),rgb(180,49,43),Enum.Material.Metal)
    part(m,"GlassCabin",Vector3.new(7*s,3*s,7*s),
        CFrame.new(x,y+5*s,z+1*s),rgb(40,82,106),Enum.Material.Glass)
    for dx=-1,1,2 do for dz=-1,1,2 do
        part(m,"Wheel",Vector3.new(3.2*s,1.2*s,3.2*s),
            CFrame.new(x+dx*4*s,y+1.5*s,z+dz*5.3*s)
            *CFrame.Angles(0,0,math.pi/2),
            rgb(24,25,27),Enum.Material.Rubber,Enum.PartType.Cylinder)
        part(m,"Hub",Vector3.new(1.2*s,.5*s,1.2*s),
            CFrame.new(x+dx*4.6*s,y+1.5*s,z+dz*5.3*s),
            rgb(163,164,165),Enum.Material.Metal)
    end end
end
local function portal(x,y,z,s)
    local m=group("SciFiPortal")
    for i=1,24 do
        local a=math.pi*2*i/24
        local item=part(m,"EnergySegment",Vector3.new(.9*s,3*s,1*s),
            CFrame.new(x+math.cos(a)*8*s,y+(11+math.sin(a)*8)*s,z)
            *CFrame.Angles(0,0,a+math.pi/2),
            i%2==0 and rgb(30,195,235) or rgb(179,69,232),Enum.Material.Neon)
        if item then item.CanCollide=false end
    end
    part(m,"Plinth",Vector3.new(22*s,2*s,10*s),
        CFrame.new(x,y+s,z),rgb(51,55,77),Enum.Material.Slate)
end
local function lights()
    Lighting.ClockTime=(THEME=="cyberpunk") and 20.5 or 16.5
    Lighting.Brightness=2.1
    Lighting.Ambient=rgb(93,100,118)
    Lighting.OutdoorAmbient=rgb(112,116,126)
    local atmosphere=Instance.new("Atmosphere")
    atmosphere.Density=.28
    atmosphere.Haze=1.25
    atmosphere.Color=rgb(206,222,247)
    atmosphere.Decay=rgb(108,137,176)
    atmosphere.Parent=Lighting
    local bloom=Instance.new("BloomEffect")
    bloom.Intensity=(THEME=="cyberpunk") and .6 or .14
    bloom.Size=25
    bloom.Threshold=1.3
    bloom.Parent=Lighting
    local grade=Instance.new("ColorCorrectionEffect")
    grade.Contrast=.10
    grade.Saturation=.07
    grade.TintColor=(THEME=="desert") and rgb(255,223,195) or rgb(233,239,255)
    grade.Parent=Lighting
end
'''
_WORLD=r'''
lights()
local STEP=QUALITY=="detailed" and 16 or 24
local half=SIZE/2
local function heightAt(x,z)
    if THEME=="city" or THEME=="cyberpunk" then return 1 end
    local n=math.noise(x*.008,z*.008,SEED*.001)*24
      +math.noise(x*.025,z*.025,SEED*.002)*7
    if THEME=="mountains" then n=n*1.8+12 end
    if THEME=="desert" then n=n*.65+3 end
    if THEME=="island" then
        local radial=math.sqrt(x*x+z*z)/(half*.86)
        n=n-30*radial*radial+8
    end
    return math.clamp(n,-12,85)
end
local cells=0
for x=-half+STEP/2,half-STEP/2,STEP do
    for z=-half+STEP/2,half-STEP/2,STEP do
        local top=heightAt(x,z)
        local material=Enum.Material.Grass
        if THEME=="desert" then material=Enum.Material.Sand
        elseif THEME=="mountains" and top>36 then material=Enum.Material.Rock
        elseif THEME=="island" and top<5 then material=Enum.Material.Sand
        elseif THEME=="city" or THEME=="cyberpunk" then
            material=Enum.Material.Concrete
        end
        Terrain:FillBlock(CFrame.new(x,(top-24)/2,z),
            Vector3.new(STEP+1,math.max(4,top+24),STEP+1),material)
        cells+=1
    end
end
if THEME=="island" then
    Terrain:FillBlock(CFrame.new(0,-8,0),
        Vector3.new(SIZE+48,16,SIZE+48),Enum.Material.Water)
end
if THEME=="city" or THEME=="cyberpunk" then
    for x=-half+16,half-16,64 do
        part(world,"Street",Vector3.new(13,.4,SIZE-24),CFrame.new(x,2.25,0),
            rgb(46,48,54),Enum.Material.Asphalt)
        for z=-half+16,half-16,20 do
            local line=part(world,"RoadMark",Vector3.new(.3,.06,7),
                CFrame.new(x,2.5,z),rgb(232,218,170),Enum.Material.SmoothPlastic)
            if line then line.CanCollide=false end
        end
    end
    for z=-half+16,half-16,64 do
        part(world,"CrossStreet",Vector3.new(SIZE-24,.4,13),
            CFrame.new(0,2.25,z),rgb(46,48,54),Enum.Material.Asphalt)
    end
    for x=-half+49,half-30,64 do for z=-half+49,half-30,64 do
        local m=group("FacadeAndWindows")
        local h=rng:NextInteger(26,70)
        part(m,"OfficeTower",Vector3.new(30,h,30),CFrame.new(x,2+h/2,z),
            THEME=="cyberpunk" and rgb(51,56,76) or rgb(136,143,153),
            Enum.Material.Concrete)
        part(m,"Cornice",Vector3.new(31,1,31),CFrame.new(x,2+h,z),
            rgb(76,83,101),Enum.Material.Metal)
        for floor=1,math.floor(h/7) do for side=-1,1,2 do
            for offset=-1,1 do
                local p=part(m,"Window",Vector3.new(.3,3.3,3.9),
                    CFrame.new(x+side*15.2,5+floor*6.5,z+offset*8.5),
                    THEME=="cyberpunk" and rgb(53,207,233) or rgb(177,198,213),
                    THEME=="cyberpunk" and Enum.Material.Neon or Enum.Material.Glass)
                if p then p.CanCollide=false end
            end
        end end
    end end
    if THEME=="cyberpunk" then portal(0,2,0,1.1) end
else
    for x=-half+24,half-24,26 do
        for z=-half+24,half-24,26 do
            if rng:NextNumber()<.65 then
                local h=heightAt(x,z)
                if THEME~="island" or h>2 then
                    if THEME=="desert" then
                        if rng:NextNumber()<.3 then rock(x,h,z,5) end
                    elseif THEME=="mountains" and h>35 then
                        rock(x,h,z,5)
                    else
                        tree(x,h,z,rng:NextNumber(.7,1.4))
                    end
                end
            end
        end
    end
    if THEME=="mountains" then castle(0,heightAt(0,0),0,.85)
    elseif THEME=="desert" then portal(0,heightAt(0,0),0,1)
    else house(0,math.max(0,heightAt(0,0)),0,.85)
    end
end
local spawn=Instance.new("SpawnLocation")
spawn.Name="JARVIS_Spawn"
spawn.Anchored=true
spawn.Neutral=true
spawn.Size=Vector3.new(12,1,12)
spawn.Position=Vector3.new(0,math.max(5,heightAt(0,0)+5),0)
spawn.Parent=world
world:SetAttribute("Theme",THEME)
world:SetAttribute("Seed",SEED)
world:SetAttribute("Quality",QUALITY)
print("JARVIS NOVA generated "..THEME..": "..cells..
      " terrain cells / "..count.." editable parts")
'''
_PROP=r'''
lights()
if MODEL=="tree" then tree(0,0,0,2)
elseif MODEL=="house" then house(0,0,0,1.5)
elseif MODEL=="castle" then castle(0,0,0,1)
elseif MODEL=="sports_car" then sportscar(0,0,0,1)
elseif MODEL=="sci_fi_portal" then portal(0,0,0,1.4)
elseif MODEL=="rocks" then rock(0,0,0,12)
end
world:SetAttribute("AssetType",MODEL)
world:SetAttribute("Quality",QUALITY)
print("JARVIS NOVA model "..MODEL.." created, parts="..count)
'''
def _name(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}",value):
        raise WorkspaceError("Имя: латинские буквы и цифры")
    return value

def _header(name,theme,quality,seed,size=0,model=""):
    return ("-- JARVIS NOVA Studio Command Bar, editable geometry\n"+
        "local NAME="+json.dumps(name)+"\n"+
        "local THEME="+json.dumps(theme)+"\n"+
        "local MODEL="+json.dumps(model)+"\n"+
        "local QUALITY="+json.dumps(quality)+"\n"+
        "local SEED="+str(seed)+"\n"+
        "local SIZE="+str(size)+"\n")

def build_world(name,*,theme="forest",size=384,quality="detailed",seed=8472):
    name=_name(name)
    if (theme not in THEMES or size not in SIZES or
        quality not in QUALITIES or type(seed) is not int or
        not 0<=seed<=1_000_000):
        raise WorkspaceError("Некорректный дизайн карты")
    script=_header(name,theme,quality,seed,size)+_COMMON+_WORLD
    description=(f"# Roblox map: {name}\n\nTheme: {theme}, size: {size} studs, "
        f"quality: {quality}, seed: {seed}.\n\n"
        "Roblox Studio: open a new Place, View > Command Bar. Paste the "
        "entire tools/GenerateWorld.luau script and execute it ONCE in Edit mode. "
        "The scenery appears as editable Parts and Smooth Terrain. "
        "Save the Place (.rbxl). Test navigation, collisions and performance.\n"
        "Script does not clear all existing Terrain, but it modifies Terrain "
        "and Lighting in the open Place; use a NEW Place for safety.\n"
        "For movie-quality PBR meshes, import licensed GLB/FBX with the "
        "Studio 3D Importer; this generator creates native Parts, not meshes.\n")
    return validate_plan(ChangePlan("luau",(
        ProposedFile("tools/GenerateWorld.luau",script),
        ProposedFile("WORLD_DESIGN.json",json.dumps(
            {"name":name,"theme":theme,"size_studs":size,
             "quality":quality,"seed":seed},ensure_ascii=False,indent=2)),
        ProposedFile("README.md",description),
    )))

def build_model(name,*,model_type="house",quality="detailed",seed=8472):
    name=_name(name)
    if (model_type not in MODELS or quality not in QUALITIES or
        type(seed) is not int or not 0<=seed<=1_000_000):
        raise WorkspaceError("Некорректная модель Roblox")
    script=_header(name,"forest",quality,seed,model=model_type)+_COMMON+_PROP
    description=(f"# Roblox 3D asset: {name}\n\nModel: {model_type}, "
        f"quality: {quality}.\n\nOpen Roblox Studio > View > Command Bar. "
        "Paste tools/GenerateModel.luau and run ONCE while editing your Place. "
        "Find Workspace/JARVIS_NOVA_* and customize individual Parts, "
        "lighting, colors and materials. Save the Place. "
        "For photorealistic custom meshes, rigging and PBR maps use Blender "
        "and import FBX/GLB into Studio manually. Play Test is required.\n")
    return validate_plan(ChangePlan("luau",(
        ProposedFile("tools/GenerateModel.luau",script),
        ProposedFile("README.md",description),
    )))
