/**
 * pdf.js's viewer component (`pdf_viewer.mjs`) does not import the library it
 * drives: it reads it off `globalThis.pdfjsLib` when it is evaluated. Imported
 * first by statementMain.mts, so the global is in place by then -- bundled
 * modules are evaluated in import order.
 */
import * as pdfjs from 'pdfjs-dist';

(globalThis as unknown as { pdfjsLib: typeof pdfjs }).pdfjsLib = pdfjs;
