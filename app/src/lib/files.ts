// Сохранение и открытие файлов: File System Access API, если есть, иначе скачивание / <input type=file>.

type Picker = (o: unknown) => Promise<{ createWritable(): Promise<{ write(b: Blob): Promise<void>; close(): Promise<void> }> }>
type OpenPicker = (o: unknown) => Promise<{ getFile(): Promise<File> }[]>

export async function saveBlob(name: string, blob: Blob, description: string, ext: string): Promise<boolean> {
  const picker = (window as unknown as { showSaveFilePicker?: Picker }).showSaveFilePicker
  if (picker) {
    try {
      const handle = await picker({ suggestedName: name, types: [{ description, accept: { [blob.type || 'application/octet-stream']: [ext] } }] })
      const w = await handle.createWritable()
      await w.write(blob)
      await w.close()
      return true
    } catch (e) {
      if ((e as DOMException).name === 'AbortError') return false
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}

export async function openTextFile(accept: string): Promise<string | null> {
  const picker = (window as unknown as { showOpenFilePicker?: OpenPicker }).showOpenFilePicker
  if (picker) {
    try {
      const [h] = await picker({ types: [{ description: 'Проект ReCAD', accept: { 'application/json': [accept] } }] })
      return await (await h.getFile()).text()
    } catch (e) {
      if ((e as DOMException).name === 'AbortError') return null
    }
  }
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = `${accept},.json`
    input.onchange = async () => resolve(input.files?.[0] ? await input.files[0].text() : null)
    input.click()
  })
}
