export const MAX_JD_IMAGES = 4;
export const MAX_JD_IMAGE_BYTES = 8 * 1024 * 1024;

const supportedTypes = new Set(["image/jpeg", "image/png", "image/gif", "image/webp"]);

export type JdImageFile = Pick<File, "name" | "size" | "type">;
export type JdImage = { id: string; filename: string; data_url: string };

export function canParseJd(rawJd: string, images: JdImage[]) {
  return Boolean(rawJd.trim() || images.length);
}

export function mergeJdImages(current: JdImage[], additions: JdImage[]) {
  const existingIds = new Set(current.map((image) => image.id));
  const uniqueAdditions = additions.filter((image) => {
    if (existingIds.has(image.id)) return false;
    existingIds.add(image.id);
    return true;
  });
  return [...current, ...uniqueAdditions].slice(0, MAX_JD_IMAGES);
}

export function removeJdImage(current: JdImage[], imageId: string) {
  return current.filter((image) => image.id !== imageId);
}

export function validateJdImageFiles(files: JdImageFile[], existingCount: number) {
  const accepted: JdImageFile[] = [];
  const errors: string[] = [];
  let available = Math.max(0, MAX_JD_IMAGES - existingCount);

  for (const file of files) {
    if (!supportedTypes.has(file.type)) {
      errors.push(`${file.name || "图片"} 不是 JPEG、PNG、GIF 或 WebP 图片。`);
    } else if (file.size > MAX_JD_IMAGE_BYTES) {
      errors.push(`${file.name || "图片"} 超过 8 MiB 限制。`);
    } else if (available <= 0) {
      errors.push(`最多可添加 ${MAX_JD_IMAGES} 张图片。`);
    } else {
      accepted.push(file);
      available -= 1;
    }
  }
  return { accepted, errors };
}

export function readJdImage(file: File): Promise<JdImage> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`${file.name || "图片"} 无法读取。`));
    reader.onload = () => resolve({
      id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
      filename: file.name || "JD 图片",
      data_url: String(reader.result),
    });
    reader.readAsDataURL(file);
  });
}
