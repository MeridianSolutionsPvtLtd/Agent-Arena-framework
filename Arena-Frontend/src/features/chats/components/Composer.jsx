import React, { useRef, useState, useLayoutEffect } from 'react';
import { Send, Paperclip, X, Loader2 } from 'lucide-react';
import { apiUploadFile } from '../../../services/api';

// Controlled auto-growing textarea + send button + file attachment support.
// Enter sends, Shift+Enter adds a newline. Value is owned by the page so
// EmptyState suggestions can prefill it.
export default function Composer({ value, onChange, onSend, disabled }) {
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleFileChange = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setUploadError(null);
    setIsUploading(true);
    try {
      const result = await apiUploadFile(files);
      if (result.files && result.files.length > 0) {
        setUploadedFiles((prev) => [...prev, ...result.files]);
      }
      if (result.errors && result.errors.length > 0) {
        const errorDetails = result.errors
          .map((err) => `${err.filename}: ${err.detail || err.code || 'Upload failed'}`)
          .join(', ');
        setUploadError(errorDetails);
      }
    } catch (err) {
      setUploadError(err.message || 'File upload failed');
    } finally {
      setIsUploading(false);
      if (e.target) e.target.value = '';
    }
  };

  const handleRemoveFile = (index) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const submit = () => {
    const text = value.trim();
    if ((!text && uploadedFiles.length === 0) || disabled || isUploading) return;
    const filesForThisMessage = [...uploadedFiles];
    setUploadedFiles([]);
    setUploadError(null);
    onSend(text, filesForThisMessage);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="shrink-0 border-t border-border bg-white px-6 py-4">
      <div className="max-w-3xl mx-auto flex flex-col gap-2.5">
        {/* Pending attachments */}
        {uploadedFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">
            {uploadedFiles.map((file, i) => {
              const name = file.filename || (typeof file === 'string' ? file : 'File Attached');
              const sizeStr = file.size_bytes
                ? file.size_bytes > 1024 * 1024
                  ? `${(file.size_bytes / (1024 * 1024)).toFixed(1)} MB`
                  : `${(file.size_bytes / 1024).toFixed(0)} KB`
                : null;
              return (
                <div
                  key={file.file_id || i}
                  className="flex items-center gap-2 bg-section-bg border border-border/60 px-3 py-1.5 rounded-xl shadow-sm animate-in slide-in-from-bottom-2 duration-300"
                >
                  <Paperclip size={12} className="text-primary shrink-0" />
                  <span className="text-[11px] font-bold text-text-primary truncate max-w-[200px]" title={file.file_id || name}>
                    {name}
                  </span>
                  {sizeStr && (
                    <span className="text-[10px] text-text-secondary font-normal">
                      ({sizeStr})
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleRemoveFile(i)}
                    className="text-text-secondary hover:text-red-500 transition-colors cursor-pointer"
                    title="Remove attachment"
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* Uploading indicator */}
        {isUploading && (
          <div className="flex items-center gap-2 px-1">
            <div className="flex items-center gap-1.5 bg-section-bg border border-border/60 px-3 py-1.5 rounded-xl shadow-sm">
              <Loader2 size={12} className="animate-spin text-primary shrink-0" />
              <span className="text-[11px] font-medium text-text-secondary">Uploading attachment…</span>
            </div>
          </div>
        )}

        {/* Upload error banner */}
        {uploadError && (
          <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs text-red-500 bg-red-50 border border-red-200/60 rounded-xl">
            <span className="truncate">⚠️ {uploadError}</span>
            <button
              type="button"
              onClick={() => setUploadError(null)}
              className="text-red-400 hover:text-red-600 shrink-0 cursor-pointer"
              title="Dismiss"
            >
              <X size={12} />
            </button>
          </div>
        )}

        {/* AI Disclaimer */}
        <p className="text-center text-[11px] text-text-secondary/70 font-normal px-2 select-none">
          Meridian AI can make mistakes. Check important information.
        </p>

        <div className="flex items-end gap-3">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isUploading}
            className="h-[46px] w-[46px] shrink-0 flex items-center justify-center rounded-2xl border border-border bg-section-bg text-text-secondary hover:text-primary hover:border-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            title="Attach file"
          >
            <Paperclip size={18} />
          </button>
          <input
            type="file"
            multiple
            ref={fileInputRef}
            onChange={handleFileChange}
            className="hidden"
          />
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Send a message…  (Enter to send, Shift+Enter for a new line)"
            className="flex-1 resize-none max-h-[200px] px-4 py-3 rounded-2xl border border-border bg-section-bg text-[15px] text-text-primary placeholder:text-text-secondary/50 outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition custom-scrollbar"
          />
          <button
            onClick={submit}
            disabled={disabled || isUploading || (!value.trim() && uploadedFiles.length === 0)}
            className="h-[46px] w-[46px] shrink-0 flex items-center justify-center rounded-2xl bg-primary text-white hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors active:scale-95 cursor-pointer"
            title="Send"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
