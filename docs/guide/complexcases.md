# Working with complex cases

When using the addon, you might encounter surfaces with geometry that containes, holes, rings and curved surfaces in a 
single surface.

This addon creates patches by finding the closest primitive to the selected surface.
If the surface it too complex, the closest primitive might not be good enough.

In this case, you will need to reduce the complexity of the surface directly in Plasticity before bridging it back to Blender.


## 1. Open Plasticity
Go to the corresponding file and surface that failed creating good topology.
