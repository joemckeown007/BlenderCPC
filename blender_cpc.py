bl_info = {
    "name": "CPC Profile Generator (Flat Receiver)",
    "author": "Joe McKeown",
    "version": (1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Add > Mesh",
    "description": "Generates a custom CPC mesh from 2D profile points with 4 user parameters.  Analytics are provided in the CPC Notes of the the Custom Properties of the Object Data panel.",
    "category": "Mesh",
}

import numpy as np
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy_extras.io_utils import ImportHelper

class MESH_OT_create_from_points(bpy.types.Operator):

    bl_idname = "mesh.cpc_profile_generator" # "mesh.create_from_points"
    bl_label = "CPC Profile Generator (Flat Receiver)"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Define the user inputs
    r_width: FloatProperty(
        name="Receiver Width",
        description="The receiver/collector width",
        default=1.0,
        min=0.01, max=1000
    )
    
    theta_c_deg: FloatProperty(
        name="Acceptance Angle Deg",
        description="Acceptance Angle Degrees",
        default=20.0,
        min=0.01, max=180.0
    )
    
    truncation_pct: FloatProperty(
        name="Truncate %",
        description="Truncate the shape height by percentage",
        default=100.0,
        min=1.0, max=100.0
    )
    
    num_points: IntProperty(
        name="Number of points in profile",
        description="Use for curve resolution",
        default=10,
        min=2, max=100
    )

    def generate_cpc_profile(self, r_width: float, theta_c_deg: float, truncation_pct: float, num_points: int):
        """
        Generates the Compound Parabolic Concentrator (CPC) profile data.

        Args:
            r_width: The width of the receiver.
            theta_c_deg: The cone angle in degrees.
            truncation_pct: The percentage for truncation.
            num_points: The number of points to use for downsampling references.

        Returns:
            A dictionary containing the structured profile data.
        """

        theta_c = np.radians(theta_c_deg)
        
        sin_tc = np.sin(theta_c)
        
        a_full = r_width / sin_tc
        C_max = 1.0 / sin_tc

        phi = np.linspace(np.pi / 2 + theta_c, 2 * theta_c, num_points * 10)

        r = (r_width * (1.0 + sin_tc)) / (1.0 - np.cos(phi))

        # Transform to Cartesian coordinates:
        x_left_full = r_width / 2.0 - r * np.sin(phi - theta_c)
        y_left_full = r * np.cos(phi - theta_c)

        # Create downsampled full references matching length "num_points":
        idx_full = np.linspace(0, len(x_left_full) - 1, num_points, dtype=int)
        x_left_ref = x_left_full[idx_full]
        y_left_ref = y_left_full[idx_full]

        # Calculate height boundaries:
        H_max = y_left_full[-1]
        H_target = H_max * (truncation_pct / 100.0)

        # 9. Filter coordinates using truncation mask: trunc_mask = y_left_full <= H_target
        trunc_mask = y_left_full <= H_target
        x_left = x_left_full[trunc_mask]
        y_left = y_left_full[trunc_mask]

        # Downsample active profile to exact resolution:
        idx_trunc = np.linspace(0, len(x_left) - 1, num_points, dtype=int)
        x_left = x_left[idx_trunc]
        y_left = y_left[idx_trunc]

        # Construct symmetrical right-side mirrors:
        x_right = -x_left
        y_right = y_left.copy()
        x_right_ref = -x_left_ref
        y_right_ref = y_left_ref.copy()

        # Store all results
        profile_data = {
            "inputs": {
                "r_width": r_width,
                "theta_c_deg": theta_c_deg,
                "truncation_pct": truncation_pct
            },
            "metrics": {
                "a_full": a_full,
                "C_max": C_max,
                "H_max": H_max,
                "H_target": H_target
            },
            "profiles": {
                "x_left": x_left,
                "y_left": y_left,
                "x_right": x_right,
                "y_right": y_right,
                "x_left_ref": x_left_ref,
                "y_left_ref": y_left_ref,
                "x_right_ref": x_right_ref,
                "y_right_ref": y_right_ref
            }
        }
        return profile_data

    def execute(self, context):
    
        data = self.generate_cpc_profile(self.r_width, self.theta_c_deg, self.truncation_pct, self.num_points)

        coords = []
        coords.append((0.0, 0.0, 0.0))
        h = 2.0
        
        for x, y in zip(data['profiles']['x_right'], data['profiles']['y_right']):
            coords.append((float(x), 0.0, float(y)))
            h = float(y)

        coords.append((0.0, 0.0, h)) # close the mesh
        
        # edges = [(i, i+1) for i in range(len(coords)-1)]
        # edges.append((0,len(coords)-1))

        # Create a new mesh and object
        mesh = bpy.data.meshes.new("ProfileMesh")
        obj = bpy.data.objects.new("ProfileObject", mesh)
        bpy.context.collection.objects.link(obj)
        
        newFace = []
        numCoords = len(coords)
        for i in range(numCoords):
            newFace.append(i)

        # Add vertices and face info to the mesh
        mesh.from_pydata(coords, [], [newFace])
        mesh.update()
        
        res_2d = self.analyze_2d_cpc(data)
        res_3d = self.analyze_3d_cpc(data)
        mesh["CPC Notes"] = self.get_analytics_cpc(data, res_2d, res_3d)

        bpy.ops.object.select_all(action='DESELECT')

        # 4. Select the new object and make it the active target
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        return {'FINISHED'}



    def analyze_2d_cpc(self, profile_data: object):
        """
        Analyzes the 2D profile data to compute 2D metrics.

        Args:
            profile_data: The master dictionary containing CPC profile data.

        Returns:
            A flat dictionary with 2D analytical results.
        """
        # 1. Read r_width and a_full from profile_data.
        r_width = profile_data["inputs"]["r_width"]
        a_full = profile_data["metrics"]["a_full"]
        
        # 2. Read x_left array from profile_data.
        x_left = profile_data["profiles"]["x_left"]

        # 3. Compute the active width at cutting plane: a_trunc = 2.0 * abs(x_left[-1])
        a_trunc = 2.0 * np.abs(x_left[-1])

        # 4. Compute new profile concentration: C_trunc = a_trunc / r_width
        C_trunc = a_trunc / r_width

        # 5. Compute lost aperture percentage: efficiency_loss = ((a_full - a_trunc) / a_full) * 100.0
        efficiency_loss = ((a_full - a_trunc) / a_full) * 100.0

        # 6. Build and return a flat dictionary containing these precise text keys:
        return {
            "a_full_2d": a_full,
            "a_trunc_2d": a_trunc,
            "r_width_2d": r_width,
            "C_max_2d": profile_data["metrics"]["C_max"],
            "C_trunc_2d": C_trunc,
            "efficiency_loss_2d": efficiency_loss
        }

    def analyze_3d_cpc(self, profile_data: object):
        """
        Analyzes the 3D profile data to compute 3D geometric ratios.

        Args:
            profile_data: The master dictionary containing CPC profile data.

        Returns:
            A flat dictionary with 3D analytical results.
        """

        r_width = profile_data["inputs"]["r_width"]
        a_full = profile_data["metrics"]["a_full"]
        x_left = profile_data["profiles"]["x_left"]

        # Calculate the active top edge width: a_trunc = 2.0 * abs(x_left[-1])
        a_trunc = 2.0 * np.abs(x_left[-1])

        # Treat lengths as radii of axisymmetric 3D shapes and calculate circular areas:
        area_full_3d = np.pi * (a_full / 2.0)**2
        area_trunc_3d = np.pi * (a_trunc / 2.0)**2
        area_receiver_3d = np.pi * (r_width / 2.0)**2

        # 3D geometric ratios:
        C_max_3d = area_full_3d / area_receiver_3d
        C_trunc_3d = area_trunc_3d / area_receiver_3d
        efficiency_loss_3d = ((area_full_3d - area_trunc_3d) / area_full_3d) * 100.0

        # 5. Build and return a flat dictionary containing these precise text keys:
        return {
            "area_full_3d": area_full_3d,
            "area_trunc_3d": area_trunc_3d,
            "area_receiver_3d": area_receiver_3d,
            "C_max_3d": C_max_3d,
            "C_trunc_3d": C_trunc_3d,
            "efficiency_loss_3d": efficiency_loss_3d
        }

    def get_analytics_cpc(self, profile_data: object, analytics_2d: object, analytics_3d: object):
        """
        Plots the Compound Parabolic Concentrator (CPC) profile and analytical results.

        Args:
            profile_data: The master dictionary containing CPC profile data.
            analytics_2d: Dictionary containing 2D analysis results.
            analytics_3d: Dictionary containing 3D analysis results.
        """

        # Extract necessary data for plotting and text box
        r_width = profile_data["inputs"]["r_width"]
        theta_c_deg = profile_data["inputs"]["theta_c_deg"]
        H_target = profile_data["metrics"]["H_target"]
        x_left = profile_data["profiles"]["x_left"]
        y_left = profile_data["profiles"]["y_left"]
        x_right = profile_data["profiles"]["x_right"]
        y_right = profile_data["profiles"]["y_right"]
        x_left_ref = profile_data["profiles"]["x_left_ref"]
        y_left_ref = profile_data["profiles"]["y_left_ref"]
        x_right_ref = profile_data["profiles"]["x_right_ref"]
        y_right_ref = profile_data["profiles"]["y_right_ref"]


        info_text = f"""
Receiver Width: {r_width:.4f}
Acceptance Angle (deg): {theta_c_deg:.2f}
Max Design Height: {profile_data['metrics']['H_max']:.4f}
Actual Profile Height (Truncated): {profile_data['metrics']['H_target']:.4f}

2D Full Aperture Width: {analytics_2d['a_full_2d']:.4f}
2D Truncated Aperture Width: {analytics_2d['a_trunc_2d']:.4f}
2D Receiver Width: {r_width:.4f}
2D Max Concentration Ratio: {analytics_2d['C_max_2d']:.4f}
2D Actual Concentration Ratio: {analytics_2d['C_trunc_2d']:.4f}
2D Efficiency Loss: {analytics_2d['efficiency_loss_2d']:.2f}%

3D Full Aperture Area: {analytics_3d['area_full_3d']:.4f}
3D Truncated Aperture Area: {analytics_3d['area_trunc_3d']:.4f}
2D Receiver Area: {np.pi * (r_width / 2.0)**2:.4f}
3D Max Concentration Ratio: {analytics_3d['C_max_3d']:.4f}
3D Actual Concentration Ratio: {analytics_3d['C_trunc_3d']:.4f}
3D Efficiency Loss: {analytics_3d['efficiency_loss_3d']:.2f}%
"""

        return info_text


# Helper function to add the tool to Blender's native Shift+A menu
def menu_func(self, context):
    self.layout.operator(MESH_OT_create_from_points.bl_idname, icon='MESH_CUBE')

# Registration functions
def register():
    bpy.utils.register_class(MESH_OT_create_from_points)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)

def unregister():
    bpy.utils.unregister_class(MESH_OT_create_from_points)
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)

if __name__ == "__main__":
    register()
