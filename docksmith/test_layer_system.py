from image.layer_system import *

# Step 1 initialize storage
init_storage()

# Step 2 create a sample file
with open("hello.txt", "w") as f:
    f.write("Hello Docksmith")

# Step 3 create layer tar
create_layer(["hello.txt"], "temp_layer.tar")

# Step 4 store layer
digest, layer_path = store_layer("temp_layer.tar")

# Step 5 get layer size
size = get_layer_size(layer_path)

# Step 6 create image manifest
manifest = create_manifest("myapp", "latest")

# Step 7 add layer to manifest
add_layer(manifest, digest, size, "COPY hello.txt /app")

# Step 8 compute manifest hash
compute_manifest_digest(manifest)

# Step 9 save manifest
save_manifest(manifest)

print("Image created successfully")

# Step 10 list images
print("\nAvailable Images:")
list_images()
