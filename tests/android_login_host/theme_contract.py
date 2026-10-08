"""Read Android resource declarations, never recreate Activity behavior."""
from pathlib import Path
import xml.etree.ElementTree as ET
NS='{http://schemas.android.com/apk/res/android}'
def themes(root,sdk=26):
    res=root/'android/app/src/main/res';styles={};colors={}
    dirs=[]
    for directory in res.glob('values*'):
        suffix=directory.name[6:]
        if suffix and not suffix.startswith('-v'):continue
        level=int(suffix[2:]) if suffix.startswith('-v') else 1
        if level<=sdk:dirs.append((level,directory))
    for _,directory in sorted(dirs):
        for path in directory.glob('*.xml'):
            for node in ET.parse(path).getroot():
                if node.tag=='color':colors[node.attrib['name']]=(node.text or '').strip()
                if node.tag=='style':styles[node.attrib['name']]=(node.attrib.get('parent',''),{item.attrib['name']:(item.text or '').strip() for item in node.findall('item')})
    def resolve(name,seen=()):
        if name in seen:raise ValueError('cyclic resource theme')
        if name.startswith('android:style/'):
            light='.Light.' in name
            return {'platform_parent':name,'android:windowBackground':'#ffffff' if light else '#000000','android:textColorPrimary':'#000000' if light else '#ffffff','android:textColorSecondary':'#757575' if light else '#bdbdbd','android:textColorHint':'#757575' if light else '#bdbdbd'}
        parent,items=styles.get(name,('android:style/Theme.Material.Light.NoActionBar',{}))
        result=resolve(parent,(*seen,name));result.update(items)
        for key,value in list(result.items()):
            if value.startswith('@color/'):result[key]=colors[value.split('/',1)[1]]
        return result
    manifest=ET.parse(root/'android/app/src/main/AndroidManifest.xml').getroot();app=manifest.find('application');result={}
    for activity in app.findall('activity'):
        theme=activity.attrib.get(NS+'theme',app.attrib[NS+'theme'])
        result[activity.attrib[NS+'name'].rsplit('.',1)[-1]]=resolve(theme.split('/',1)[1])
    return result

def properties(root):
    result=[]
    for activity,theme in themes(root,36).items():
        for suffix,key in [('text','android:textColorPrimary'),('hint','android:textColorHint'),('window','android:windowBackground')]:
            value=theme[key]
            if value.startswith('#'):
                value=value[1:];value=('ff'+value) if len(value)==6 else value
                result.append('-Dfixture.'+activity+'.'+suffix+'='+value)
    return result
