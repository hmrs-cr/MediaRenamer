using System.CommandLine;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace MediaRenamer;

// A helper record to store information about files to be processed.
// Using a record provides concise, immutable data structures.
internal record FileToProcess(string OriginalPath, string Suffix);

public class Program
{
    static async Task<int> Main(string[] args)
    {
        var nfoFilesArgument = new Argument<FileInfo[]>("nfo-files", "One or more paths to the NFO files to be processed.")
        {
            Arity = ArgumentArity.OneOrMore
        };
        nfoFilesArgument.ExistingOnly();

        var dryRunOption = new Option<bool>(
            aliases: new[] { "-d", "--dry-run" },
            description: "Show what files would be renamed and moved without actually performing the actions.");

        var rootCommand = new RootCommand("Renames and moves media files and their accessories into a dedicated folder based on NFO metadata.")
        {
            nfoFilesArgument,
            dryRunOption
        };

        rootCommand.SetHandler((nfoFiles, dryRun) =>
        {
            if (dryRun)
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine(">>> DRY RUN MODE ENABLED. NO FILES WILL BE CHANGED. <<<\n");
                Console.ResetColor();
            }

            foreach (var nfoFile in nfoFiles)
            {
                RenameAndMoveFilesFromNfo(nfoFile, dryRun);
            }
        }, nfoFilesArgument, dryRunOption);

        return await rootCommand.InvokeAsync(args);
    }

    static void RenameAndMoveFilesFromNfo(FileInfo nfoFileInfo, bool isDryRun)
    {
        Console.WriteLine($"--- Processing: '{nfoFileInfo.FullName}' ---");
        try
        {
            var directory = nfoFileInfo.DirectoryName ?? ".";
            var originalBaseName = Path.GetFileNameWithoutExtension(nfoFileInfo.Name);

            var doc = XDocument.Load(nfoFileInfo.FullName);
            var movieElement = doc.Element("movie");

            if (movieElement == null)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("ERROR: Could not find the root <movie> tag. Skipping.");
                Console.ResetColor();
                return;
            }

            // Extract metadata from NFO
            var title = (string?)movieElement.Element("title");
            var year = (string?)movieElement.Element("year");
            var codec = (string?)movieElement.Descendants("codec").FirstOrDefault();
            var width = (string?)movieElement.Descendants("width").FirstOrDefault();
            var height = (string?)movieElement.Descendants("height").FirstOrDefault();
            var tmdbId = movieElement.Elements("uniqueid").FirstOrDefault(e => (string?)e.Attribute("type") == "tmdb")?.Value;
            var audioLang = (string?)movieElement.Descendants("audio").FirstOrDefault(a => (string?)a.Element("default") == "True")?.Element("language")
                                ?? (string?)movieElement.Descendants("language").FirstOrDefault();

            title = ToTitleCase(title);

            if (string.IsNullOrEmpty(title) || string.IsNullOrEmpty(year) || string.IsNullOrEmpty(codec) ||
                string.IsNullOrEmpty(width) || string.IsNullOrEmpty(height) || string.IsNullOrEmpty(audioLang) || 
                string.IsNullOrEmpty(tmdbId))
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("ERROR: Could not find all required tags for renaming. Skipping.");
                Console.ResetColor();
                return;
            }
            
            var sanitizedFolderName = SanitizeFileName($"{title} ({year})");
            var destinationDirectoryPath = Path.Combine(directory, $"{year}", sanitizedFolderName);
            if (!isDryRun)
            {
                Directory.CreateDirectory(destinationDirectoryPath);
            }
            else
            {
                Console.WriteLine($"  [DRY RUN] Would ensure directory exists: '{destinationDirectoryPath}'");
            }
            
            // {title} ({year}) [tmdbid={tmdbid}] - {width}x{height}.{codec}.{default_audio_language}
            var newBaseName = SanitizeFileName($"{title} ({year}) [tmdbid={tmdbId}] - {width}x{height}.{codec.ToUpper()}.{audioLang.ToUpper()}");

            // --- NEW: Advanced file discovery logic ---
            var filesToProcess = FindAssociatedFiles(directory, originalBaseName);

            if (filesToProcess.Count == 0)
            {
                Console.ForegroundColor = ConsoleColor.DarkYellow;
                Console.WriteLine($"WARNING: No files found associated with base name '{originalBaseName}'.");
                Console.ResetColor();
                return;
            }

            foreach (var file in filesToProcess)
            {
                var fileExtension = Path.GetExtension(file.OriginalPath);
                // Append the discovered suffix (e.g., "-poster", ".en") to the new base name
                var newBaseNameWithSuffix = newBaseName + file.Suffix;

                // Handle potential file name collisions within the destination directory
                var finalFileName = $"{newBaseNameWithSuffix}{fileExtension}";
                int counter = 1;
                while (File.Exists(Path.Combine(destinationDirectoryPath, finalFileName)))
                {
                    // Append counter after suffix: My Movie-poster (1).jpg
                    finalFileName = $"{newBaseNameWithSuffix} ({counter}){fileExtension}";
                    counter++;
                }
                
                var finalFilePath = Path.Combine(destinationDirectoryPath, finalFileName);
                var originalFileName = Path.GetFileName(file.OriginalPath);

                if (isDryRun)
                {
                    Console.WriteLine($"  [DRY RUN] Would move: '{originalFileName}'");
                    Console.WriteLine($"                    to: '{finalFilePath}'");
                }
                else
                {
                    File.Move(file.OriginalPath, finalFilePath);
                    Console.ForegroundColor = ConsoleColor.Green;
                    Console.WriteLine($"  Moved: '{originalFileName}'");
                    Console.ResetColor();
                    Console.WriteLine($"     to: '{finalFilePath}'");
                }
            }
        }
        catch (Exception ex)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine($"An unexpected error occurred: {ex.Message}");
            Console.ResetColor();
        }
        finally
        {
            Console.WriteLine(new string('-', nfoFileInfo.FullName.Length + 18));
        }
    }
    
    /// <summary>
    /// Finds all files associated with a base name, including those with suffixes.
    /// </summary>
    static List<FileToProcess> FindAssociatedFiles(string directory, string originalBaseName)
    {
        var filesToProcess = new List<FileToProcess>();
        
        // Define extensions to exclude from suffix-based matching (they must be an exact match)
        var excludedExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".mkv", ".mp4", ".nfo" };

        foreach (var filePath in Directory.EnumerateFiles(directory))
        {
            var fileName = Path.GetFileName(filePath);
            var fileNameWithoutExt = Path.GetFileNameWithoutExtension(fileName);
            var ext = Path.GetExtension(fileName);

            // Case 1: Exact match (e.g., "Valiente.mkv"). This is always included.
            if (fileNameWithoutExt.Equals(originalBaseName, StringComparison.OrdinalIgnoreCase))
            {
                filesToProcess.Add(new FileToProcess(filePath, Suffix: ""));
            }
            // Case 2: Starts-with match for non-excluded files (e.g., "Valiente-poster.jpg")
            else if (fileNameWithoutExt.StartsWith(originalBaseName, StringComparison.OrdinalIgnoreCase) && !excludedExtensions.Contains(ext))
            {
                // The suffix is the part of the name after the original base name
                var suffix = fileNameWithoutExt[originalBaseName.Length..];
                filesToProcess.Add(new FileToProcess(filePath, suffix));
            }
        }
        return filesToProcess;
    }

    static string SanitizeFileName(string fileName)
    {
        fileName = fileName.Replace(":", " -");
        var invalidChars = new string(Path.GetInvalidFileNameChars());
        var regex = new Regex($"[{Regex.Escape(invalidChars)}]");
        return regex.Replace(fileName, "").Trim();
    }

    static string ToTitleCase(string? text) =>
        string.IsNullOrWhiteSpace(text) ? string.Empty : System.Globalization.CultureInfo.CurrentCulture.TextInfo.ToTitleCase(text);
}