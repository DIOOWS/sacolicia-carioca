import cloudinary
import cloudinary.uploader
from flask import current_app


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def _configure():
    values = {
        "cloud_name": current_app.config.get("CLOUDINARY_CLOUD_NAME"),
        "api_key": current_app.config.get("CLOUDINARY_API_KEY"),
        "api_secret": current_app.config.get("CLOUDINARY_API_SECRET"),
    }
    if not all(values.values()):
        raise RuntimeError("Cloudinary ainda não foi configurado no servidor.")
    cloudinary.config(secure=True, **values)


def validate_product_image(file):
    if not file or not file.filename:
        return None
    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        return "Envie uma imagem JPG, PNG ou WEBP."
    if file.mimetype and not file.mimetype.startswith("image/"):
        return "O arquivo enviado não é uma imagem válida."
    return None


def upload_product_image(file):
    _configure()
    result = cloudinary.uploader.upload(
        file,
        folder="sacolicia-carioca/produtos",
        resource_type="image",
        unique_filename=True,
        overwrite=False,
        transformation=[
            {"width": 1000, "height": 1000, "crop": "limit"},
            {"quality": "auto", "fetch_format": "auto"},
        ],
    )
    return result["secure_url"], result["public_id"]


def delete_product_image(public_id):
    if not public_id:
        return
    _configure()
    cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
