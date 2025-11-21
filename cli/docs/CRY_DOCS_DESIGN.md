

# **Architectural Design and Implementation Strategy for CLI-Based Documentation Migration: The CRYSTAL Solutions Case Study**

## **1\. Introduction: The Convergence of Scientific Documentation and Terminal Workflows**

The evolution of software documentation has increasingly trended toward "Docs-as-Code" paradigms, where documentation is treated with the same rigor, version control, and tooling as the software source code itself. In the specific domain of scientific computing—where the CRYSTAL package operates as a premier tool for ab initio quantum chemistry calculations—the user base consists predominantly of researchers and engineers who spend a significant portion of their workflow within terminal environments.1 Consequently, the migration of static, web-based documentation, such as the site hosted at tutorials.crystalsolutions.eu, into a localized, command-line accessible format represents not merely a format conversion, but a fundamental enhancement of the Developer Experience (DX).  
This report presents a comprehensive architectural analysis and implementation roadmap for transforming the legacy HTML documentation of the CRYSTAL solutions suite into a structured, nested Markdown repository. The ultimate objective is to facilitate a Command Line Interface (CLI) tool capable of rendering this content using the gum and glow utilities. The report synthesizes research into web crawling methodologies, Abstract Syntax Tree (AST) transformation, referential integrity in hyperlinked documents, and Textual User Interface (TUI) design.  
The challenge presented by the crystalsolutions repository is multifaceted. It involves deep recursive hierarchies characteristic of scientific tutorials (spanning 0D molecules to 3D crystals), complex formatting likely involving mathematical notation, and the inherent "impedance mismatch" between the HyperText Markup Language (HTML) and Markdown.1 To address this, we evaluate the efficacy of mirror-based ingestion versus semantic extraction, referencing tools ranging from the foundational GNU Wget to modern AI-driven scrapers like Crawl4AI and Trafilatura. Furthermore, we scrutinize the presentation layer, distinguishing the functional roles of gum for navigation and glow for pagination, while considering alternatives such as smd for specialized rendering needs.4

## **2\. Domain Analysis: The CRYSTAL Solutions Ecosystem**

Before architecting the migration pipeline, it is imperative to understand the nature of the source material. The structure, density, and interconnectedness of the documentation dictate the technical requirements for the crawler and the converter.

### **2.1 Content Typology and Periodicity**

The CRYSTAL package is a sophisticated software suite designed for quantum simulation in solid-state chemistry. Its documentation is not merely a flat collection of text files but a structured pedagogical resource. The manuals and tutorials cover systems of varying periodicity:

* **0D Systems:** Molecules and clusters.  
* **1D Systems:** Polymers, nanotubes, and helices.  
* **2D Systems:** Slabs and surfaces.  
* **3D Systems:** Crystals and bulk materials.1

This distinct categorization suggests a directory structure on the web server (e.g., /tutorials/3d\_crystals/, /tutorials/surfaces/) that carries semantic meaning. A "flattened" migration—where all files are dumped into a single directory—would destroy the logical progression of the tutorials. Therefore, the selected extraction tool must possess **Strict Directory Preservation** capabilities. The migration architecture must ensure that a tutorial on "Elasticity" located in the "Properties" subdirectory remains in that specific nested relationship to the "Geometry Optimization" tutorials to maintain the pedagogical flow intended by the authors.1

### **2.2 Mathematical and Scientific Notation**

Scientific documentation inherently relies on mathematical formalism. The CRYSTAL manuals discuss Hartree-Fock or Kohn-Sham Hamiltonians, Bloch functions, and Gaussian-type functions (GTF).2 In the source HTML, these are likely represented either as images (in older legacy sites), MathML, or LaTeX rendered via JavaScript libraries (like MathJax).  
This presents a critical rendering challenge for the CLI target. Standard Markdown supports basic text formatting, but rendering complex equations in a terminal is non-trivial.

* **Risk Assessment:** If the source uses images for equations, a standard text-based conversion will result in \!\[equation\](equation.gif). The glow reader can display alt-text, but the mathematical meaning is lost unless the user's terminal supports image protocols (like Sixel or iTerm2 inline images).  
* **Conversion Requirement:** The transformation layer must attempt to convert HTML-embedded math into LaTeX-style Markdown blocks (e.g., $E \= mc^2$). While glow has limited support for complex LaTeX rendering compared to a browser, retaining the raw LaTeX string is preferable to losing the information entirely. Alternative viewers like smd (Simple Markdown Viewer) explicitly tout "Rich text rendering" and "Image rendering (when possible)," which might offer advantages over glow for this specific scientific dataset.4

### **2.3 The "PDF vs. HTML" Dilemma**

The research indicates that CRYSTAL documentation is also distributed as substantial PDF manuals, such as the "CRYSTAL17 User Manual" and "CRYSTAL23 User Manual".2 These documents are often hundreds of pages long.

* **Implication for Migration:** The web tutorials likely link to these PDFs for deep technical reference. A recursive crawler like wget will download these PDFs. However, gum and glow cannot read PDFs.  
* **Strategic Decision:** The migration tool has two options:  
  1. **Exclusion:** Configure the crawler to ignore .pdf files to save space, assuming the user only wants the interactive HTML tutorials.  
  2. **Conversion (Advanced):** Utilize a tool like **Marker** 7, which specializes in converting PDFs to Markdown. Marker uses deep learning (and optionally LLMs) to extract layouts, tables, and equations from PDFs. Integrating Marker would allow the creation of a truly comprehensive local knowledge base, converting the static manuals into searchable Markdown alongside the tutorials. Given the user's request to "pull all of the docs pages," excluding PDFs might result in broken references. However, converting them adds significant computational overhead. For this architecture, we will prioritize the HTML conversion but note the PDF integration as a "Day 2" enhancement.

## **3\. Extraction Architecture: The Ingestion Layer**

The first phase of the migration pipeline is Extraction (Ingestion). The objective is to retrieve the raw HTML and asset files from tutorials.crystalsolutions.eu while maintaining the exact directory structure. We analyze three distinct approaches: Classical Mirroring, Semantic Spidering, and AI-Augmented Scraping.

### **3.1 Classical Mirroring: The Wget Standard**

GNU Wget is the industry standard for recursive mirroring. It operates by following links found in HTML documents and saving the files to a local directory that mimics the server's path structure.

#### **3.1.1 Configuration for Strict Mirroring**

To successfully mirror tutorials.crystalsolutions.eu, specific flags are required to handle the "static site" nature of the target.

* **\--mirror (-m):** This is a meta-flag that turns on recursion (-r) and time-stamping (-N), ensuring that subsequent runs only download updated files. This is crucial for maintaining the documentation store over time.8  
* **\--no-parent (-np):** This is critical. If the crawler starts at .../tutorials/, it must not ascend to the parent crystalsolutions.eu homepage, which might contain marketing material irrelevant to the documentation. This guarantees the scope is restricted to the tutorial hierarchy.8  
* **\--page-requisites (-p):** This ensures that CSS, images, and scripts needed to render the page are downloaded. While we eventually convert to Markdown, downloading images is essential to preserve the diagrams used in the 0D/1D/2D system explanations.9

#### **3.1.2 The Link Conversion Fallacy**

A major pitfall identified in the research is the behavior of the \--convert-links (-k) flag.

* **Function:** It rewrites links to point to the *local* file system rather than the *remote* server. For example, href="/css/style.css" becomes href="../css/style.css".  
* **The Problem:** Wget assumes the destination format is still HTML. If it rewrites a link to point to chapter1.html, and we subsequently convert chapter1.html to chapter1.md, the link in the final Markdown file will point to a non-existent HTML file.  
* **Analysis:** As noted in the research, "Wget... only non-anchor tags seem to have been touched" in some configurations, and fundamentally, it targets offline *browser* viewing, not offline *terminal* viewing.10 Therefore, relying on Wget for link rewriting is insufficient. The link rewriting logic must be deferred to the Transformation phase (Section 4), where we can programmatically swap extensions.

### **3.2 Semantic Spidering: Trafilatura and Traversal**

Trafilatura represents a modern approach to ingestion, focusing on extracting the "main text" and discarding "boilerplate" (navbars, footers, ads).

* **Relevance:** For a documentation site, the navigation sidebar is redundant because the CLI tool (gum) will provide its own navigation interface. Trafilatura's ability to extract just the content is highly valuable.12  
* **Recursive Limitation:** While Trafilatura has a \--crawl option, the research indicates it produces a *list* of URLs or a flat output.14 It does not natively replicate a nested directory structure on the file system as faithfully as Wget. It is designed more for corpus generation (for NLP) than for website mirroring.  
* **Integration:** Using Trafilatura would require a custom Python wrapper to feed it URLs, receive the text, and write it to the correct os.path. This increases implementation complexity compared to the "fire and forget" nature of Wget.

### **3.3 AI-Augmented Scraping: Crawl4AI**

Crawl4AI offers a bridge between mirroring and semantic extraction, designed specifically to generate Markdown for LLMs.15

* **Mechanism:** It uses deep crawling strategies (BFS) and heuristics to strip noise.  
* **Markdown Native:** Unlike Wget (HTML output) or Trafilatura (Text/XML output), Crawl4AI outputs Markdown directly.  
* **Trade-off:** As with Trafilatura, it is a library, not a standalone mirroring tool. It requires a Python driver script to manage the file I/O and directory creation.

### **3.4 Comparative Selection**

For the specific requirement of "organized nested directory structure," **Wget** remains the superior ingestion tool due to its robust handling of file system paths, retries, and massive file sets without custom coding. The "noise" (navbars/footers) can be stripped during the Markdown conversion phase using AST filters. The reliability of Wget in replicating the exact hierarchy of the crystalsolutions tutorial tree outperforms the flat-list tendency of modern scrapers.

## **4\. Transformation Engineering: The HTML-to-Markdown Pipeline**

Once the HTML artifacts are mirrored locally, the core engineering challenge begins: transforming the DOM into a terminal-readable format (Markdown) while preserving information fidelity.

### **4.1 The Impedance Mismatch**

HTML and Markdown are not isomorphic. HTML allows for complex nesting (\<div\> inside \<a\> inside \<table\>), whereas Markdown is line-oriented.

* **Tables:** Scientific tutorials often use tables for data. HTML tables can be complex (merged cells). Standard Markdown tables are rigid. The converter must handle these gracefully or flatten them.  
* **Divs and Spans:** HTML relies on div and span for styling. Markdown ignores these. However, sometimes semantic meaning is hidden in classes (e.g., \<div class="warning"\>). A naive converter strips this. A sophisticated converter (like Pandoc) can map these to blockquotes (\> Warning:...).

### **4.2 Pandoc: The AST-Based Transformation**

Pandoc is the most powerful tool for this task because it operates on an Abstract Syntax Tree (AST). It parses the HTML into an internal representation, allows for manipulation, and then writes out Markdown.17

#### **4.2.1 The "Fenced Divs" Issue**

Research indicates a specific compatibility issue when converting complex HTML to Markdown using Pandoc, known as "Fenced Divs."

* **The Issue:** By default, if Pandoc encounters a div it wants to preserve, it uses a syntax like ::: {.class} content :::.  
* **The Conflict:** Many Markdown viewers (including potentially glow or smd) do not strictly support this extension, leading to "gibberish" or raw text rendering in the terminal.18  
* **Mitigation:** The conversion command must explicitly disable this extension if the viewer doesn't support it, using \-t gfm-raw\_html or similar flags to force a more standard GitHub Flavored Markdown (GFM) output which glow handles natively.18

#### **4.2.2 Lua Filters for Custom Logic**

Pandoc's killer feature is Lua filtering. This allows us to intervene in the conversion process.

* **Application:** We can write a simple Lua script that looks for every Link element in the AST. If the link target ends in .html, the script changes it to .md. This solves the "Link Integrity" problem (Section 3.1.2) at the AST level, which is far more robust than using regex (sed) on the raw text.19

### **4.3 Alternative: Python-Based Logic (markdownify)**

For users who prefer a pure Python pipeline, markdownify offers a customized approach.

* **Custom Converters:** One can subclass MarkdownConverter to define exactly how specific tags (like \<div class="tutorial-step"\>) should be rendered.20  
* **Heuristics:** Unlike Pandoc's rigid AST, markdownify uses BeautifulSoup. This is more forgiving of "bad" HTML often found in legacy academic sites.  
* **Performance:** Python iteration over thousands of files is generally slower than Pandoc's Haskell-based engine, but likely negligible for a documentation site of this size.

### **4.4 Recursive Batch Processing**

Since Pandoc processes one file at a time, the transformation layer requires a wrapper.

* **Bash Implementation:** A find loop is the standard Unix approach.  
  Bash  
  find./docs \-name "\*.html" \-exec pandoc {} \-o {.}.md \\;

* **Recursion Logic:** This command recursively descends into every subdirectory (/tutorials/, /tutorials/1D/, etc.), finds HTML files, and converts them in place. This preserves the directory structure created by Wget.21

## **5\. Ensuring Referential Integrity: The Linking Layer**

The usability of the CLI tool hinges on the user's ability to navigate from one document to another. If a tutorial on "Basis Sets" links to "Hamiltonians," that link must work in the terminal.

### **5.1 The Relative Link Problem**

In the source HTML, a link might look like \<a href="../Hamiltonians.html"\>See Hamiltonians\</a\>.  
When converted to Markdown, if we simply copy the href, we get (../Hamiltonians.html).

* **CLI Behavior:** When a user clicks this link in a terminal viewer:  
  * **Browser Fallback:** Some viewers will try to open the default web browser because they see .html.  
  * **File Open Failure:** If the viewer tries to open it as a local file, it will fail because the file Hamiltonians.html might have been deleted (replaced by .md) or the viewer doesn't know how to render HTML.  
* **Requirement:** The link *must* be rewritten to ../Hamiltonians.md.

### **5.2 Algorithmic Solutions**

There are two primary ways to achieve this rewriting:

#### **5.2.1 Post-Processing (The sed Approach)**

After conversion, one can run a global search-and-replace on all Markdown files.

* **Command:** grep \-r \-l ".html". | xargs sed \-i 's/\\.html/.md/g'  
* **Risk:** This is "dumb" text replacement. It might accidentally rename text that isn't a link (e.g., "The file is named index.html"). However, given the context of documentation, this risk is often acceptable.23

#### **5.2.2 In-Flight AST Modification (The Pandoc/Lua Approach)**

As mentioned in 4.2.2, utilizing a Lua filter is the "correct" engineering solution.

* **Mechanism:** The filter inspects the Link object. It checks the target attribute. If the target matches the regex \\.html$, it swaps the extension.  
* **Benefit:** This guarantees that only actual hyperlinks are modified, preserving textual references to filenames.19

### **5.3 Handling Non-Markdown Assets**

The crystalsolutions site contains images and potentially downloadable input files (for the chemistry software).

* **Images:** Wget downloads these to the local directory. Markdown references them as \!\[alt\](image.png). glow will display the alt text.  
* **Input Files:** Links to .d12 or .out files (CRYSTAL specific formats) should *not* be rewritten to .md. The link rewriter must be selective, only targeting .html files.

## **6\. The Presentation Layer: TUI Design and User Experience**

The user specified gum as the rendering tool. However, a deep analysis of the CharmBracelet ecosystem reveals that gum and glow serve distinct, complementary purposes.

### **6.1 Gum: The Navigational Interface**

gum is a composable tool for shell scripts. It excels at capturing user input.

* **The Filter Command:** gum filter takes a list of strings (filenames) and provides a fuzzy-searchable menu. This is the ideal mechanism for the user to find a specific tutorial within the nested structure.5  
* **Styling:** gum style allows for the creation of a "Welcome Banner" or instructional headers, using borders, padding, and colors to make the CLI tool feel like a polished application rather than a raw script.  
* **Limitations:** gum has a format command for Markdown, but it is intended for small snippets (like help text), not long-form reading. It lacks paging controls (scroll up/down) for large documents.

### **6.2 Glow: The Content Consumer**

glow is a dedicated Markdown reader.

* **Pagination:** It uses a pager (like less) allowing the user to scroll through long tutorials, search within the text, and stash documents.  
* **Rendering:** It supports GFM, syntax highlighting for code blocks (crucial for the CRYSTAL input deck examples), and intelligent wrapping.24  
* **Integration:** The ideal workflow is to use gum to select the file, and then pass that file path to glow for reading.

### **6.3 Alternative Viewers: smd vs. glow**

While glow is the standard, the snippet 4 highlights smd (Simple Markdown Viewer) as a Rust-based alternative.

* **Pros of smd:** It claims support for "Image rendering (when possible)" and "Rich text rendering." In a scientific context involving molecular diagrams, if smd can render pixel graphics in a supported terminal (like Kitty), it would be superior to glow.  
* **Recommendation:** For the baseline implementation, glow is recommended due to its maturity and ecosystem alignment with gum. However, the architecture should be modular enough to swap glow for smd if image rendering becomes a priority.4

## **7\. Implementation Strategy: The CLI-Docs-Engine**

Based on the analysis, we propose a three-phase implementation plan. This solution uses wget for ingestion, pandoc for transformation, and a Bash script wrapping gum and glow for the interface.

### **Phase 1: The Mirroring Script (The Harvester)**

This script downloads the content. It is designed to be idempotent—running it twice only downloads changes.

Bash

\#\!/bin/bash  
\# mirror.sh \- Ingests the crystalsolutions site

TARGET\_URL="https://tutorials.crystalsolutions.eu/"  
LOCAL\_DIR="./crystal\_docs"

\# Create directory  
mkdir \-p "$LOCAL\_DIR"

echo "Starting Recursive Mirror of $TARGET\_URL..."  
echo "This may take time depending on network speed."

wget \\  
  \--mirror \\  
  \--convert-links \\  
  \--adjust-extension \\  
  \--page-requisites \\  
  \--no-parent \\  
  \--directory-prefix="$LOCAL\_DIR" \\  
  \--no-host-directories \\  
  "$TARGET\_URL"

echo "Mirror complete. HTML files located in $LOCAL\_DIR"

*Note: We include \--convert-links here to fix asset paths (images/css) for local validity, but we will overwrite the HTML links in the next step.*.8

### **Phase 2: The Conversion Engine (The Transformer)**

This script walks the directory tree, converts HTML to Markdown, and performs link surgery.

Bash

\#\!/bin/bash  
\# convert.sh \- Transforms HTML to Markdown and fixes links

DOC\_ROOT="./crystal\_docs"

echo "Starting Conversion..."

\# 1\. Recursively find and convert HTML files  
find "$DOC\_ROOT" \-name "\*.html" | while read \-r html\_file; do  
    \# Construct new filename with.md extension  
    md\_file="${html\_file%.html}.md"  
      
    echo "Converting: $html\_file \-\> $md\_file"  
      
    \# Use Pandoc with GFM (GitHub Flavored Markdown)  
    \# \--wrap=none ensures lines don't wrap hard, letting the terminal handle it  
    pandoc "$html\_file" \\  
      \-f html \\  
      \-t gfm-raw\_html \\  
      \--wrap=none \\  
      \-o "$md\_file"  
        
    \# Optional: Delete original HTML to save space/confusion  
    \# rm "$html\_file"  
done

\# 2\. Link Surgery: Replace.html links with.md links in the generated files  
\# This uses a cautious sed pattern to avoid false positives  
echo "Rewriting internal links..."  
if\]; then  
  \# macOS sed requires empty string for \-i  
  find "$DOC\_ROOT" \-name "\*.md" \-exec sed \-i '' 's/\\.html)/.md)/g' {} \+  
else  
  \# GNU sed  
  find "$DOC\_ROOT" \-name "\*.md" \-exec sed \-i 's/\\.html)/.md)/g' {} \+  
fi

echo "Conversion Complete."

*Technical Note on sed: The pattern \\.html) specifically targets Markdown links which end in ), e.g., \[Link\](target.html). This prevents changing text like "See index.html" in a code block.*.21

### **Phase 3: The Interactive Viewer (The User Interface)**

This is the tool the user actually runs. It uses gum to create a searchable navigation tree.

Bash

\#\!/bin/bash  
\# crystal-cli \- The Interactive Viewer

DOC\_ROOT="./crystal\_docs"

\# Use Gum Style to create a header  
gum style \\  
	\--foreground 212 \--border-foreground 212 \--border double \\  
	\--align center \--width 50 \--margin "1 2" \--padding "2 4" \\  
	"CRYSTAL Solutions" "CLI Documentation Explorer"

while true; do  
    \# list files, strip the./crystal\_docs prefix for cleaner display  
    \# sort handles the hierarchy display  
    files=$(find "$DOC\_ROOT" \-name "\*.md" | sed "s|^$DOC\_ROOT/||" | sort)  
      
    \# Gum Filter: Fuzzy search the file list  
    selection=$(echo "$files" | gum filter \\  
        \--indicator="→" \\  
        \--placeholder="Search tutorials (e.g. 'elasticity')..." \\  
        \--header="Select a file to read (ESC to quit)" \\  
        \--height=20)

    \# Handle exit  
    if \[ \-z "$selection" \]; then  
        echo "Exiting..."  
        exit 0  
    fi

    \# Reconstruct full path  
    full\_path="$DOC\_ROOT/$selection"

    \# Render with Glow  
    \# \-p enables pager mode  
    glow "$full\_path" \-p  
done

*UX Note:* This script creates an infinite loop, allowing the user to read a file, quit the pager (q), and immediately return to the search menu to find another topic, simulating a browsing experience.5

## **8\. Alternative Architectures and Comparisons**

While the Wget/Pandoc/Gum stack is the primary recommendation, other architectures offer specific advantages depending on user priorities.

### **8.1 The "Personal Knowledge Base" Approach (Obsidian)**

Research highlights tools like the **Obsidian Importer** plugin or the **Recursive Copy** plugin.27

* **Workflow:** Instead of a CLI tool, the user mirrors the site and opens the folder as an Obsidian Vault. Obsidian's internal link updater automatically handles relative link integrity.  
* **Pros:** Powerful GUI, graph view of tutorial connections, easy editing.  
* **Cons:** Breaks the requirement for a "CLI tool." It is "heavy" compared to a terminal script. However, it is worth noting that the Markdown files generated by our Phase 2 script are fully compatible with Obsidian.

### **8.2 The Node.js Wrapper Approach**

Snippet 29 mentions client-side libraries like marked. One could build a Node.js CLI application (using commander or inquirer) that bundles the renderer.

* **Pros:** Single binary distribution (via pkg).  
* **Cons:** Heavy dependency chain (Node\_modules). The Bash/Gum approach utilizes tools likely already present or easily installable on a developer's machine (Go binaries).

### **8.3 Comparison of Rendering Engines**

| Feature | Glow | Gum Format | SMD (Rust) | Bat |
| :---- | :---- | :---- | :---- | :---- |
| **Primary Role** | Markdown Reader | Text Formatter | Markdown Viewer | Syntax Highlighting Cat |
| **Pagination** | Yes (Native) | No | Yes | Yes (via less) |
| **GFM Support** | Excellent | Basic | Excellent | Good |
| **Image Support** | Alt Text | No | Rich Text (Experimental) | No |
| **Math Rendering** | Basic | None | Enhanced | Raw Text |
| **Ecosystem** | CharmBracelet | CharmBracelet | Standalone | Sharkdp |

Table 1: Comparison of Terminal Markdown Rendering Tools based on snippets.4

## **9\. Future Proofing and Maintenance**

The documentation at tutorials.crystalsolutions.eu is dynamic. A static snapshot will eventually become outdated.

* **Sync Strategy:** The mirror.sh script uses wget \--timestamping. Running this script periodically (e.g., via a Cron job) will download only new or changed HTML files.  
* **Incremental Builds:** The convert.sh script currently converts *everything*. An optimization for "Day 2 Operations" would be to check if the .md file is older than the .html file before converting, drastically reducing update times.

## **10\. Conclusion**

The migration of the CRYSTAL solutions documentation to a CLI-native format is a feasible and high-impact project. By leveraging **Wget** for its recursive mirroring robustness, **Pandoc** for its AST-based transformation fidelity, and the **CharmBracelet stack (Gum/Glow)** for a modern TUI experience, we can deliver a tool that honors the complex, nested structure of the scientific source material. This architecture not only preserves the pedagogical hierarchy of the tutorials but also integrates seamlessly into the terminal-centric workflows of the quantum chemists utilizing the software.  
This approach solves the critical "Referential Integrity" problem through targeted post-processing and ensures that the dense scientific information remains accessible, searchable, and readable in a low-latency environment.

#### **Works cited**

1. CRYSTAL09 \- Crystal Solutions, accessed November 19, 2025, [https://www.crystalsolutions.eu/upload/2012-09-19\_09-09-15\_crystal09\_manual.pdf](https://www.crystalsolutions.eu/upload/2012-09-19_09-09-15_crystal09_manual.pdf)  
2. CRYSTAL17 \- Crystal Solutions, accessed November 19, 2025, [https://www.crystalsolutions.eu/upload/CRYSTAL%2017%20-%20User%20Manual.pdf](https://www.crystalsolutions.eu/upload/CRYSTAL%2017%20-%20User%20Manual.pdf)  
3. CRYSTAL23 \- Crystal Solutions, accessed November 19, 2025, [https://crystalsolutions.eu/upload/2022-12-14\_12-12-29\_crystal23.pdf](https://crystalsolutions.eu/upload/2022-12-14_12-12-29_crystal23.pdf)  
4. Introducing smd: A Simple Markdown Viewer for Your Terminal : r/commandline \- Reddit, accessed November 19, 2025, [https://www.reddit.com/r/commandline/comments/1f3n0z5/introducing\_smd\_a\_simple\_markdown\_viewer\_for\_your/](https://www.reddit.com/r/commandline/comments/1f3n0z5/introducing_smd_a_simple_markdown_viewer_for_your/)  
5. charmbracelet/gum: A tool for glamorous shell scripts \- GitHub, accessed November 19, 2025, [https://github.com/charmbracelet/gum](https://github.com/charmbracelet/gum)  
6. CRYSTAL17 \- Crystal Solutions, accessed November 19, 2025, [https://www.crystalsolutions.eu/upload/2017-09-19\_11-09-25\_CRYSTAL17%20-%20User%20Manual.pdf](https://www.crystalsolutions.eu/upload/2017-09-19_11-09-25_CRYSTAL17%20-%20User%20Manual.pdf)  
7. datalab-to/marker: Convert PDF to markdown \+ JSON quickly with high accuracy \- GitHub, accessed November 19, 2025, [https://github.com/datalab-to/marker](https://github.com/datalab-to/marker)  
8. Mirroring With wget and Avoiding Parent Directories | Baeldung on Linux, accessed November 19, 2025, [https://www.baeldung.com/linux/wget-mirroring](https://www.baeldung.com/linux/wget-mirroring)  
9. Mirroring a Website with Wget \- Kevin Cox, accessed November 19, 2025, [https://kevincox.ca/2022/12/21/wget-mirror/](https://kevincox.ca/2022/12/21/wget-mirror/)  
10. How to force wget to convert \*all\* downloaded links to relative ones?, accessed November 19, 2025, [https://unix.stackexchange.com/questions/336798/how-to-force-wget-to-convert-all-downloaded-links-to-relative-ones](https://unix.stackexchange.com/questions/336798/how-to-force-wget-to-convert-all-downloaded-links-to-relative-ones)  
11. Here's Why wget \--convert-links Isn't Converting Your Links | by Daniel Malmer \- Medium, accessed November 19, 2025, [https://danielmalmer.medium.com/heres-why-wget-s-convert-links-option-isn-t-converting-your-links-cec832ee934c](https://danielmalmer.medium.com/heres-why-wget-s-convert-links-option-isn-t-converting-your-links-cec832ee934c)  
12. A Python package & command-line tool to gather text on the Web — Trafilatura 2.0.0 documentation, accessed November 19, 2025, [https://trafilatura.readthedocs.io/](https://trafilatura.readthedocs.io/)  
13. Simplify Website Scraping With Trafilatura \- Julien Blanchard, accessed November 19, 2025, [https://blanchardjulien.com/posts/20231029\_trafilatura.html](https://blanchardjulien.com/posts/20231029_trafilatura.html)  
14. Web crawling — Trafilatura 2.0.0 documentation \- Read the Docs, accessed November 19, 2025, [https://trafilatura.readthedocs.io/en/latest/crawls.html](https://trafilatura.readthedocs.io/en/latest/crawls.html)  
15. unclecode/crawl4ai: Crawl4AI: Open-source LLM Friendly Web Crawler & Scraper. Don't be shy, join here: https://discord.gg/jP8KfhDhyN \- GitHub, accessed November 19, 2025, [https://github.com/unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)  
16. Markdown Generation \- Crawl4AI Documentation (v0.7.x), accessed November 19, 2025, [https://docs.crawl4ai.com/core/markdown-generation/](https://docs.crawl4ai.com/core/markdown-generation/)  
17. Pandoc User's Guide, accessed November 19, 2025, [https://pandoc.org/MANUAL.html](https://pandoc.org/MANUAL.html)  
18. Converting html to md with Pandoc, problems in Obisidian \- Help \- Obsidian Forum, accessed November 19, 2025, [https://forum.obsidian.md/t/converting-html-to-md-with-pandoc-problems-in-obisidian/74117](https://forum.obsidian.md/t/converting-html-to-md-with-pandoc-problems-in-obisidian/74117)  
19. Convert Markdown links to HTML with Pandoc \- Stack Overflow, accessed November 19, 2025, [https://stackoverflow.com/questions/40993488/convert-markdown-links-to-html-with-pandoc](https://stackoverflow.com/questions/40993488/convert-markdown-links-to-html-with-pandoc)  
20. HTML to Markdown with html2text \- python \- Stack Overflow, accessed November 19, 2025, [https://stackoverflow.com/questions/45034227/html-to-markdown-with-html2text](https://stackoverflow.com/questions/45034227/html-to-markdown-with-html2text)  
21. Converting all files in a folder to md using pandoc on Mac \- Stack Overflow, accessed November 19, 2025, [https://stackoverflow.com/questions/26126362/converting-all-files-in-a-folder-to-md-using-pandoc-on-mac](https://stackoverflow.com/questions/26126362/converting-all-files-in-a-folder-to-md-using-pandoc-on-mac)  
22. Bash \- How do I loop through sub directories and execute this command \[duplicate\], accessed November 19, 2025, [https://unix.stackexchange.com/questions/552345/bash-how-do-i-loop-through-sub-directories-and-execute-this-command](https://unix.stackexchange.com/questions/552345/bash-how-do-i-loop-through-sub-directories-and-execute-this-command)  
23. convert html links to markdown using command sed \- Stack Overflow, accessed November 19, 2025, [https://stackoverflow.com/questions/40273926/convert-html-links-to-markdown-using-command-sed](https://stackoverflow.com/questions/40273926/convert-html-links-to-markdown-using-command-sed)  
24. charmbracelet/glow: Render markdown on the CLI, with pizzazz\! \- GitHub, accessed November 19, 2025, [https://github.com/charmbracelet/glow](https://github.com/charmbracelet/glow)  
25. Glow: Pretty Markdown Rendering In The Terminal \- YouTube, accessed November 19, 2025, [https://www.youtube.com/watch?v=EDNpK3iH7A0](https://www.youtube.com/watch?v=EDNpK3iH7A0)  
26. How to Use Wget to Mirror Websites for Offline Browsing \- DEV Community, accessed November 19, 2025, [https://dev.to/rijultp/how-to-use-wget-to-mirror-websites-for-offline-browsing-48l4](https://dev.to/rijultp/how-to-use-wget-to-mirror-websites-for-offline-browsing-48l4)  
27. Import HTML files \- Obsidian Help, accessed November 19, 2025, [https://help.obsidian.md/import/html](https://help.obsidian.md/import/html)  
28. Recursive Copy \- Obsidian Stats, accessed November 19, 2025, [https://www.obsidianstats.com/plugins/recursive-copy](https://www.obsidianstats.com/plugins/recursive-copy)  
29. Marked Documentation, accessed November 19, 2025, [https://marked.js.org/](https://marked.js.org/)