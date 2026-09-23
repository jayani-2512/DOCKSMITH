from image.layer_system import *

init_storage()

manifest = create_manifest("myapp", "latest")

save_manifest(manifest)

list_images()
