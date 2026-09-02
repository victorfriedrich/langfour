import DOMPurify from 'dompurify';

export function sanitizeHTML(htmlString: string): string {
  return DOMPurify.sanitize(htmlString, {
    RETURN_TRUSTED_TYPE: true,
  }) as unknown as string;
}
